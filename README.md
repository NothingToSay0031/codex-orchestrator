# Codex Orchestrator

将 [OpenCode Orchestrator](https://github.com/NothingToSay0031/opencode-orchestrator) 的多 agent 协作体系迁移到 [OpenAI Codex CLI](https://github.com/openai/codex)。

**核心设计**：默认 session 即 Orchestrator（无需 spawn），通过 `spawn_agent` 委托给 6 个 specialist agent。

## 架构

```
             Default Session (Orchestrator)
                        |
          +----------+--+--+----------+
          |          |     |          |
      explorer  librarian  oracle   fixer/designer/observer
     (read-only)(read-only)(read-only) (write/read-only)
```

## 文件清单

```
codex-orchestrator/
├─ config-inject.toml      # 全局 config 注入模板（instructions + agents 注册）
├─ install.ps1             # 安装脚本
├─ README.md               # 本文件
└─ .codex/
   └─ agents/
      ├─ explorer.toml      # 只读代码库侦察  | deepseek-v4-flash
      ├─ librarian.toml     # 只读外部文档    | deepseek-v4-flash + MCP
      ├─ oracle.toml        # 只读架构评审    | gpt-5.6-terra
      ├─ fixer.toml         # 可写机械实现    | deepseek-v4-pro
      ├─ designer.toml      # 可写 UI/UX      | deepseek-v4-flash
      └─ observer.toml      # 只读视觉分析    | MiniMax-M3
```

## 安装

### 1. 部署 agent 文件

```powershell
.\install.ps1 -Scope global
```

复制 6 个 agent `.toml` 到 `~/.codex/agents/`。

### 2. 合并全局配置

打开 `config-inject.toml`，将其中的三段内容**合并**到 `~/.codex/config.toml`：

- `instructions` -- 行为规则 + Orchestrator 角色 prompt（覆盖模型出厂 prompt，默认 session 即 orchestrator）
- `[agents]` -- 注册 6 个 specialist

合并后重启 Codex。

## 使用

默认 session 就是 Orchestrator，直接对话即可：

```
Add user authentication with JWT to the Express API. Include login, register, refresh, and middleware.
```

Orchestrator 会自动分解任务并 spawn 对应的 specialist。

也可以手动 spawn：

```
spawn_agent({"agent_type": "explorer", "message": "Map the authentication flow across all route files."})
spawn_agent({"agent_type": "librarian", "message": "Find the official Express.js JWT middleware docs."})
spawn_agent({"agent_type": "oracle", "message": "Review src/auth/middleware.ts for security issues."})
```

## Specialist 一览

| Agent | model | effort | sandbox | skills | MCP |
|---|---|---|---|---|---|
| **explorer** | deepseek-v4-flash | max | read-only | -- | -- |
| **librarian** | deepseek-v4-flash | max | read-only | bundled | context7 + websearch + grep_app |
| **oracle** | gpt-5.6-terra | high | read-only | -- | -- |
| **fixer** | deepseek-v4-pro | max | workspace-write | -- | -- |
| **designer** | deepseek-v4-flash | -- | workspace-write | bundled | -- |
| **observer** | MiniMax-M3 | -- | read-only | -- | -- |

### 每个 agent TOML 结构

1. `name` + `description` + `model` + `model_reasoning_effort` + `sandbox_mode`
2. `instructions` = 行为规则 + 角色专属 prompt（覆盖出厂 prompt）
3. `[skills]` -- `include_instructions` + `bundled.enabled`
4. librarian 额外 `[mcp_servers]`

## 关键设计决策

| 维度 | 说明 |
|---|---|
| 默认 session = orchestrator | 全局 `instructions` 内含 orchestrator 角色，无需 spawn |
| 只读 agent | `sandbox_mode = "read-only"`，禁止文件写入 |
| MCP 隔离 | 全局 config 无 MCP，librarian 独占 context7 + websearch + grep_app |
| Skill 精简 | 只给 librarian/designer 启用 bundled skills，其余禁用 |
| 覆盖模型出厂 prompt | 每个 agent TOML 的 `instructions` 替换 models 的 base_instructions |
