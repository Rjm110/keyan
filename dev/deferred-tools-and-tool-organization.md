# Deferred Tools 与工具组织指南

本文说明 CubePi 中 `DeferredToolsMiddleware`、`deferred_tool_groups` 的工作方式，并给出大型 Agent 项目的工具组织建议。

适用源码版本：当前仓库实现。

## 1. 为什么需要 Deferred Tools

当 Agent 只有少量工具时，可以直接注册：

```python
agent = Agent(
    model=model,
    tools=[read_file, search_files, run_command],
)
```

当工具数量增长到几十个甚至上百个时，一开始就把全部工具的完整 schema 发送给模型，会带来几个问题：

- system prompt 和 tools schema 变长；
- 每次模型调用都携带大量工具定义；
- token 消耗和请求延迟增加；
- 模型更难从大量工具中选择正确的一个；
- 工具集合变化时，prompt cache 可能失效；
- 不同领域的工具描述会互相干扰。

`DeferredToolsMiddleware` 采用渐进式工具披露（progressive tool disclosure）：

```text
初始只提供工具目录和加载入口
    -> 模型判断需要某个工具组
    -> 加载对应工具组
    -> 使用其中的具体工具
```

它并不是把工具删除，而是把工具从“启动时全部暴露”改成“需要时再加载”。

## 2. `DeferredToolsMiddleware` 在哪里

类定义位于：

```text
cubepi/deferred/middleware.py
```

定义形式是：

```python
class DeferredToolsMiddleware(Middleware):
```

它虽然继承自 `Middleware`，但属于 Deferred Tools 功能子系统。该目录还包含：

```text
cubepi/deferred/
    _catalog.py          # 工具组目录渲染
    _dispatch_tool.py    # deferred_tool_call 工具
    _expand_tool.py      # load_tools 工具
    middleware.py        # DeferredToolsMiddleware
    types.py             # DeferredToolGroup 等类型
```

因此它放在 `cubepi/deferred/`，而不是 `cubepi/middleware/`，表达的是业务归属，而不是技术类型。

## 3. 它内部提供哪些工具

`DeferredToolsMiddleware` 初始化时会创建 `load_tools`：

```python
self.tools = [
    _make_load_tools(load_callback=self._expand_callback)
]
```

默认策略是 `dispatch`，此时还会创建 `deferred_tool_call`：

```python
if strategy == "dispatch":
    self.tools.append(
        _make_deferred_tool_call(
            known_tool_names=lambda: list(self._tool_to_group)
        )
    )
```

所以它内部固定提供的工具是：

| 策略 | 内部工具 |
|---|---|
| `dispatch`，默认 | `load_tools`、`deferred_tool_call` |
| `inject` | `load_tools` |

真正的业务工具，例如 `read_file`、`search_files`、`run_command`，不是写死在这个 Middleware 里，而是由用户提供的 loader 返回。

## 4. `deferred_tool_groups` 是什么

`deferred_tool_groups` 是 Agent 的一个构造参数：

```python
agent = Agent(
    model=model,
    deferred_tool_groups=[...],
)
```

它的类型是：

```python
list[DeferredToolGroup] | None
```

一个 `DeferredToolGroup` 表示一组初始折叠、按需展开的工具：

```python
@dataclass
class DeferredToolGroup:
    group_id: str
    display_name: str
    description: str
    tool_names: list[str]
    loader: Callable[[], Awaitable[list[AgentTool]]]
```

### 字段说明

#### `group_id`

工具组的唯一 ID，例如：

```python
group_id="file_tools"
```

模型之后通过这个 ID 请求加载工具组。

#### `display_name`

工具组的可读名称，例如：

```python
display_name="文件工具"
```

#### `description`

工具组用途的说明，例如：

```python
description="用于读取、搜索和修改项目文件"
```

它会被渲染到工具目录或相关提示中，帮助模型判断何时需要加载该组。

#### `tool_names`

声明这一组可能包含的工具名称：

```python
tool_names=["read_file", "search_files", "write_file"]
```

这是目录信息，不代表这些工具启动时已经进入模型可见的工具列表。

#### `loader`

真正返回工具对象的异步函数：

```python
async def load_file_tools() -> list[AgentTool]:
    return [read_file, search_files, write_file]
```

loader 可以延迟导入模块、初始化客户端、检查权限、判断外部服务是否可用，或者动态生成工具。

## 5. Agent 如何自动创建 Deferred Middleware

这里的“自动”不是扫描项目代码，也不是推断哪些工具应该延迟加载，而是 `Agent.__init__()` 检查了一个明确的参数。

源码逻辑位于 `cubepi/agent/agent.py`：

```python
if deferred_tool_groups:
    from cubepi.deferred.middleware import DeferredToolsMiddleware

    deferred_mw = DeferredToolsMiddleware(
        groups=deferred_tool_groups,
        extra_ref=lambda: self._extra,
        strategy=deferred_tool_strategy,
        on_tools_expanded=...,
    )
    middleware = [*(middleware or []), deferred_mw]
```

随后 Agent 会统一收集所有 Middleware 的 `tools`：

```python
for mw in middleware:
    middleware_tools.extend(getattr(mw, "tools", []) or [])
```

并把它们加入 Agent 的工具列表。

完整流程是：

```text
deferred_tool_groups 非空
    -> Agent 自动创建 DeferredToolsMiddleware
    -> 追加到 middleware 列表
    -> 读取它的 tools 属性
    -> 注册 load_tools 和 deferred_tool_call
```

因此，用户通常不需要手动写：

```python
middleware=[DeferredToolsMiddleware(...)]
```

但这只是 Deferred Tools 提供的专用快捷 API。其他 Middleware 通常仍需要用户显式实例化并放入 `middleware`。

## 6. `dispatch` 与 `inject` 两种策略

### 6.1 `inject`

配置：

```python
agent = Agent(
    model=model,
    deferred_tool_groups=groups,
    deferred_tool_strategy="inject",
)
```

调用流程：

```text
模型调用 load_tools
    -> loader 返回 read_file、search_files
    -> 工具加入 Agent 的工具集合
    -> 下一轮模型直接调用 read_file
```

优点：

- 逻辑直观；
- 使用原生工具调用；
- 模型直接看到真实工具名称。

缺点：

- 工具集合扩展后，模型可见的 tools 数组会变化；
- 可能触发 prompt cache 重新计算；
- 工具加载越多，后续上下文越大。

### 6.2 `dispatch`

默认配置是：

```python
agent = Agent(
    model=model,
    deferred_tool_groups=groups,
    deferred_tool_strategy="dispatch",
)
```

调用流程：

```text
模型调用 load_tools
    -> 工具加载到 Agent 内部
    -> 模型调用 deferred_tool_call
    -> resolve_tool_call 将调用重写为真实工具
    -> 真实工具执行
```

可以表示为：

```text
deferred_tool_call
    -> resolve_tool_call
    -> read_file
```

优点：

- 初始 tools 数组和 system prompt 可以保持稳定；
- 更有利于 prompt caching；
- 不必在每次扩展后重新暴露全部工具 schema；
- 适合工具数量很大的 Agent。

缺点：

- 调用链更复杂；
- 依赖 `resolve_tool_call`；
- 调试时需要理解 dispatch 和真实工具之间的映射。

## 7. 完整示例

假设已有三个工具：

```python
read_file
search_files
run_command
```

先按领域定义 loader：

```python
from cubepi.deferred.types import DeferredToolGroup


async def load_file_tools() -> list[AgentTool]:
    return [read_file, search_files]


async def load_command_tools() -> list[AgentTool]:
    return [run_command]
```

再定义工具组：

```python
file_group = DeferredToolGroup(
    group_id="file_tools",
    display_name="文件工具",
    description="用于读取和搜索项目文件",
    tool_names=["read_file", "search_files"],
    loader=load_file_tools,
)

command_group = DeferredToolGroup(
    group_id="command_tools",
    display_name="命令工具",
    description="用于执行项目开发和检查命令",
    tool_names=["run_command"],
    loader=load_command_tools,
)
```

最后交给 Agent：

```python
agent = Agent(
    model=model,
    system_prompt="You are a coding agent.",
    deferred_tool_groups=[file_group, command_group],
)
```

启动时主要注册：

```text
load_tools
deferred_tool_call  # 仅 dispatch 策略
```

模型需要文件能力时先加载：

```text
load_tools(group_id="file_tools")
```

之后 loader 返回 `read_file` 和 `search_files`，Middleware 再按照当前策略让 Agent 使用这些工具。

## 8. 项目有很多新工具时，应该怎么组织

推荐原则是：

> 普通业务工具使用 `@tool`；工具数量过多时使用 `DeferredToolGroup` 延迟加载；只有需要统一生命周期、动态资源或跨工具策略时，才创建自定义 Middleware。

不要因为工具数量变多，就把所有工具都塞进一个 Middleware。工具实现和 Agent 生命周期策略应该分开。

### 8.1 普通工具使用 `@tool`

```python
@tool
async def read_file(path: str) -> str:
    ...


@tool
async def search_files(query: str) -> str:
    ...


@tool
async def run_tests(test_path: str = "") -> str:
    ...
```

然后直接注册：

```python
agent = Agent(
    model=model,
    tools=[read_file, search_files, run_tests],
)
```

适合：

- 工具是独立动作；
- 工具没有复杂共享状态；
- 工具只服务于当前 Agent；
- 工具不需要改变 Agent 循环；
- 工具数量不多。

这是默认推荐方式。

### 8.2 按领域拆分工具模块

工具多时，先按业务领域拆分文件，而不是先创建 Middleware：

```text
tools/
    filesystem.py
    shell.py
    git.py
    database.py
    browser.py
    deployment.py
```

例如：

```python
# tools/filesystem.py

@tool
async def read_file(...):
    ...


@tool
async def search_files(...):
    ...
```

```python
# tools/git.py

@tool
async def git_status(...):
    ...


@tool
async def git_diff(...):
    ...
```

组合时统一导入：

```python
from tools.filesystem import read_file, search_files
from tools.git import git_diff, git_status

agent = Agent(
    model=model,
    tools=[read_file, search_files, git_status, git_diff],
)
```

这种方式能让每个工具保持独立，也方便单元测试和权限审查。

### 8.3 工具很多且不想全部暴露时使用 Deferred Tools

当工具数量达到几十或上百个时，可以按领域建立工具组：

```text
file_tools
git_tools
database_tools
browser_tools
deployment_tools
```

loader 仍然返回普通 `@tool` 创建的工具：

```python
async def load_git_tools() -> list[AgentTool]:
    from tools.git import git_diff, git_status, git_commit

    return [git_status, git_diff, git_commit]
```

然后通过 `DeferredToolGroup` 注册：

```python
git_group = DeferredToolGroup(
    group_id="git_tools",
    display_name="Git 工具",
    description="用于查看和修改 Git 仓库状态",
    tool_names=["git_status", "git_diff", "git_commit"],
    loader=load_git_tools,
)
```

这里的推荐关系是：

```text
@tool
    -> 定义具体工具
DeferredToolGroup
    -> 定义工具组和延迟加载方式
DeferredToolsMiddleware
    -> 管理加载、注入或分发
```

### 8.4 工具和 Agent 生命周期强相关时使用 Middleware

以下情况适合创建自定义 Middleware：

- 同时提供一组相关工具；
- 需要修改 system prompt；
- 需要修改上下文；
- 需要在工具执行前统一审批；
- 需要在工具执行后修改结果；
- 需要控制模型是否继续循环；
- 需要保存跨轮状态；
- 需要管理外部客户端或其他动态资源。

例如部署领域可以把工具和规则放在一起：

```python
class DeploymentMiddleware(Middleware):
    def __init__(self, deploy_client):
        self._deploy_client = deploy_client
        self.tools = [
            make_deploy_tool(deploy_client),
            make_rollback_tool(deploy_client),
        ]

    async def transform_system_prompt(
        self,
        system_prompt,
        *,
        ctx,
        signal=None,
    ):
        return (
            system_prompt
            + "\\n部署前必须检查环境。"
            + "\\n生产环境操作需要审批。"
        )

    async def before_tool_call(self, ctx, *, signal=None):
        if ctx.tool_call.name == "deploy_production":
            return BeforeToolCallResult(
                block=True,
                reason="生产环境部署需要人工审批",
            )
        return None
```

这个 Middleware 不只是工具集合，还封装了：

```text
部署工具
    + 部署规则
    + 权限控制
    + 上下文约束
```

## 9. 推荐的项目结构

随着工具和 Agent 能力增加，可以采用下面的分层：

```text
my_agent/
    agent.py
    tools/
        filesystem.py
        shell.py
        git.py
        database.py
        browser.py
        deployment.py
    middleware/
        approval.py
        deployment.py
        project_context.py
    deferred/
        groups.py
```

职责划分：

```text
tools/
    具体工具实现

middleware/
    Agent 生命周期和跨工具策略

deferred/groups.py
    工具分组和 loader

agent.py
    组合最终 Agent
```

一个实际组合可以是：

```python
agent = Agent(
    model=model,
    tools=[
        read_file,
        search_files,
    ],
    middleware=[
        CompactionMiddleware(...),
        ApprovalPolicyMiddleware(...),
        DeploymentMiddleware(...),
    ],
    deferred_tool_groups=[
        git_tools_group,
        database_tools_group,
    ],
)
```

最终结构如下：

```text
直接 tools
    ├── read_file
    └── search_files

显式 Middleware
    ├── CompactionMiddleware
    ├── ApprovalPolicyMiddleware
    └── DeploymentMiddleware
          └── deploy、rollback 等工具

Agent 自动创建的 DeferredToolsMiddleware
    ├── load_tools
    └── deferred_tool_call
```

## 10. 最终决策规则

可以按下面的顺序判断：

```text
这是一个独立动作吗？
    是 -> 使用 @tool

参数模型复杂、工具需要动态生成或需要完全控制执行协议吗？
    是 -> 手动使用 AgentTool(...)

工具很多，需要按需加载吗？
    是 -> 使用 @tool + DeferredToolGroup.loader

除了工具，还要改变 Agent 生命周期或统一管理状态吗？
    是 -> 创建自定义 Middleware

只是想审批现有工具吗？
    是 -> 使用 ApprovalPolicyMiddleware

只是想压缩上下文吗？
    是 -> 使用 CompactionMiddleware
```

对一个持续扩展的编码 Agent，推荐演进顺序是：

```text
1. 使用 @tool 编写新工具
2. 按功能领域拆分到 tools/ 目录
3. 工具数量变多后引入 DeferredToolGroup
4. 加入 CompactionMiddleware
5. 加入 ApprovalPolicyMiddleware
6. 只有出现跨工具状态或生命周期逻辑时，才创建自定义 Middleware
```

最终可以记住这句话：

> 工具实现属于 `tools`；工具延迟加载策略属于 `DeferredToolsMiddleware`；跨工具和 Agent 生命周期规则属于自定义 Middleware。
