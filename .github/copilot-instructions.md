# Commit Message 规范

提交 Commit Message 时，必须使用 Conventional Commits 格式：

```text
<type>(<scope>): <description>
```

- `type` 必须使用英文标准类型。
- `scope` 可选，用于表示修改范围。
- `description` 尽量使用简洁中文，以祈使语气说明本次提交做了什么。
- 结尾不要添加句号。
- 不要使用“修改代码”“更新一下”“修复问题”等模糊描述。

常用 `type`：

- `feat`：新增功能
- `fix`：修复 Bug
- `docs`：修改文档
- `style`：仅修改代码格式，不影响功能
- `refactor`：代码重构，不新增功能也不修复 Bug
- `perf`：性能优化
- `test`：新增或修改测试
- `build`：构建系统或依赖相关修改
- `ci`：CI 配置相关修改
- `chore`：其他维护性修改
- `revert`：撤销之前的提交

推荐格式：

```text
feat(player): 添加玩家冲刺功能
fix(ui): 修复暂停菜单无法关闭的问题
refactor(enemy): 重构敌人状态机
perf(pool): 减少对象池重复实例化
docs(readme): 补充项目运行说明
test(save): 添加存档系统测试
build(unity): 更新项目依赖配置
chore(git): 更新 gitignore
```

如果修改范围不明确，可以省略 `scope`：

```text
feat: 添加难度选择功能
fix: 修复游戏结束后无法重新开始的问题
refactor: 简化事件系统实现
```

如果存在 Breaking Change，应在类型和冒号之间添加 `!`，并在 Commit Message 正文中说明：

```text
feat(api)!: 修改存档接口

BREAKING CHANGE: 修改存档数据结构，旧版本存档不再兼容
```

生成 Commit Message 时，优先保持简洁，通常只生成一行：

```text
type(scope): 中文描述
```
