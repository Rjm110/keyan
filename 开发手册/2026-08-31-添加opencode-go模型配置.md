# 添加 OpenCode Go 模型配置选项（2026-08-31）

> 开发内容：在科研助手前端模型配置中新增 "OpenCode Go" 厂商选项，用户订阅 OpenCode Go（$10/月）后从 opencode.ai/auth 获取 API key，前端选择厂商 + 输入 key 即可使用。
>
> 开发时间：2026-08-31

---

## 一、需求背景

用户希望在前端模型配置中新增 **OpenCode Go** 选项。OpenCode Go 是 opencode 官方推出的低成本开源编程模型订阅服务（$10/月），提供稳定的全球访问。

**官方文档关键信息**（https://opencode.ai/docs/zh-cn/go）：
- API 端点：`https://opencode.ai/zen/go/v1/chat/completions`（OpenAI 兼容格式）
- API key：从 [OpenCode Zen](https://opencode.ai/auth) 订阅 Go 后获取
- 模型 ID：`deepseek-v4-flash`、`glm-5.3-flash`、`kimi-k3` 等（API 调用用裸 ID）
- 模型分 3 种 API 格式：
  - `chat/completions`（OpenAI 兼容）：GLM 系列、Kimi 系列、DeepSeek V4 系列、MiMo、LongCat、Hy
  - `messages`（Anthropic 格式）：Qwen 系列、MiniMax M3/M2.7
  - `responses`（OpenAI Responses 格式）：Grok 4.6、GPT 5.6 Luna、Muse Spark

## 二、用户决策

| 决策点 | 选择 |
| --- | --- |
| MVP 支持范围 | 仅 `chat/completions` 格式（GLM/Kimi/DeepSeek V4/MiMo/LongCat/Hy 等 15 个模型） |
| 默认模型 | `deepseek-v4-flash`（价格低 $0.22/M、月额度高约 7600 请求） |
| 验证方式 | 已订阅 Go 有 key，端到端验证 |

## 三、实现方案

### 1. `cubepi/providers/presets.py` — 添加 opencode 预设

在 `_PRESETS` 字典中添加：

```python
"opencode": ProviderPreset(
    name="OpenCode Go",
    provider_id="opencode",
    api_key_env="OPENCODE_API_KEY",
    base_url_env="OPENCODE_BASE_URL",
    base_url="https://opencode.ai/zen/go/v1",
    model="deepseek-v4-flash",
    capability=CapabilityDescriptor(supports_tools=True),
),
```

**关键点**：base_url 用 `https://opencode.ai/zen/go/v1`（OpenAI SDK 会自动拼 `/chat/completions`）。

### 2. `app/config.py` — 添加 opencode 选项

- `_PRESET_NAMES` 集合添加 `"opencode"`（走 OpenAI 兼容预设路径）
- `PROVIDER_OPTIONS` 列表添加：

```python
{
    "id": "opencode",
    "name": "OpenCode Go",
    "default_model": "deepseek-v4-flash",
},
```

- `build_model()` 的 RuntimeError 提示信息更新（加入 opencode）

### 3. 前端 `app/static/index.html` — 零改动

provider 下拉框由 `GET /config` 动态填充，`loadConfig` 遍历 `PROVIDER_OPTIONS` 自动渲染新选项。

## 四、验证方式

1. **静态检查**：`uv run mypy app/ cubepi/providers/presets.py`（0 错误）、`uv run ruff check`（全过）、`uv run pytest app/tests/ -q`（14 passed）。
2. **Provider 构建验证**：`create_provider('opencode', api_key='sk-test')` 成功构建，`model('deepseek-v4-flash')` 返回正确 BoundModel。
3. **浏览器验证**：
   - 刷新页面 → 下拉框出现 "OpenCode Go" ✅
   - 选择 OpenCode Go + 输入真实 key → 保存成功（`✅ 已保存：opencode`）✅
   - `GET /config` 返回 providers 列表含 opencode，key 脱敏正确（`sk-j…AukO`）✅

## 五、问题与解决

| 问题 | 原因 | 解决 |
| --- | --- | --- |
| 对话请求超时 `ConnectTimeout` | 当前网络环境无法直连 `opencode.ai`（国际站点，与 google.com 一样被网络限制） | 非代码问题。DNS 解析正常（Cloudflare IPv6），IPv4/IPv6 均连接超时。需在可访问国际网络的网络环境下使用 |
| 设置代理后仍超时 | Clash Verge 代理在运行（端口 7897），但服务器启动时**没有设置代理环境变量**，Python/curl 都没走代理 | 启动服务器时设置代理环境变量：`export HTTP_PROXY=http://127.0.0.1:7897 HTTPS_PROXY=http://127.0.0.1:7897 ALL_PROXY=http://127.0.0.1:7897` |

### 代理配置说明

`openai.AsyncOpenAI` 默认 `trust_env=True`，会自动读取 `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` 环境变量。因此**只需在启动 uvicorn 时设置代理环境变量**即可：

```bash
export HTTP_PROXY=http://127.0.0.1:7897
export HTTPS_PROXY=http://127.0.0.1:7897
export ALL_PROXY=http://127.0.0.1:7897
uv run uvicorn app.server:app --host 127.0.0.1 --port 8000
```

**验证结果**（设置代理后）：
- `curl -x http://127.0.0.1:7897 https://opencode.ai` → HTTP 200（0.9s）
- `curl -x http://127.0.0.1:7897 https://opencode.ai/zen/go/v1/models` → 返回模型列表
- 浏览器端到端：`✔ list_files 完成` → `✔ read_file 完成` → 完整内容输出 ✅

## 六、下一步

1. **网络环境**：opencode.ai 需要可访问国际网络的网络环境才能使用（需设置代理环境变量）。
2. **支持更多格式**：后续可支持 `messages`（Anthropic 格式，Qwen/MiniMax）和 `responses`（Grok/GPT）格式模型。
3. **模型列表提示**：可在配置卡片给 opencode 加"可用模型"提示（如 placeholder 提示可用模型）。