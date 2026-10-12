# exteraGram 插件技能包

给 **exteraGram 插件开发者**用的三个 AI 助手技能（Skill）。

## 内容

| 目录 | 作用 | 规模 |
|---|---|---|
| `exteragram-plugin-dev/` | **开发**：BasePlugin SDK、事件 hook、设置页、菜单项、Class Proxy、Elyx 结构化插件、日志、依赖管理 | `SKILL.md` + 17 个 `reference/` + 4 个 `examples/` |
| `exteragram-plugin-debug/` | **排障**：adb 部署管线、logcat 三通道、宿主反编译取证、Chaquopy 互操作陷阱、性能优化、UI 自动化 | 单文件 `SKILL.md` |
| `exteragram-plugin-workflow/` | **搭工作流**：6 阶段施工图，把整套插件开发环境从零搭起来，每阶段给命令与验收判据 | 单文件 `SKILL.md` |

## 怎么用

这三个是**技能文档**，供支持 Skill 机制的 AI 助手加载（Claude Skills / DSH / 其他 agent 框架）。

- **支持技能目录的工具**：把目录整个放进你的技能目录，助手会按 frontmatter 里的
  `description` 自动判断何时启用。
- **不支持的工具**：直接把对应 `SKILL.md` 的内容贴进对话作为上下文；
  `reference/` 下的文件按需追加（它们是 SKILL.md 里链接的细化章节）。

三者是配套关系：`workflow` 讲**怎么把工作流搭起来**，`dev` 是 **API 手册**，
`debug` 是**排障手册**。

## exteragram-plugin-dev

覆盖范围：

- **基线**：官方文档 SDK `1.4.4.3`；已在真机 `1.4.5.7` 上逐条校正（文中标注 *verified on device*）
- **元数据与生命周期**：`__id__`/`__name__` 等顶层常量、AST 解析规则、`on_plugin_load`/`on_plugin_unload`
- **事件 hook**：`pre_request_hook` / `post_request_hook` / `on_update_hook` / `on_updates_hook` / `on_send_message_hook`
- **设置页**：`Header`/`Switch`/`Selector`/`Input`/`EditText`/`Text`/`Custom` + `SimpleSettingFactory`
- **Class Proxy**：`@java_subclass`、`@joverride`/`@joverload`/`@jmethod`/`jfield`、MVEL、`JA`/`JGS`/`JIR`/`JS` 修饰符
- **多账号**：`account=` 参数、`self.client(account)`
- **Elyx**：`refmap.yml`/`metainfo.yml`/`assets`/`strings`、`ElyxBuilder` CLI
- **其他**：`client_utils`、`file_utils`、`hook_utils`、`intents`、`ui.alert`、`ui.bulletin`、文本格式化

其中 `reference/logging.md` 与 `reference/undocumented-modules.md` 是**官方文档未覆盖**、
经真机内省补充的章节（`log_utils` / `plugin_settings` / `markdown_utils` 等模块）。

### 几处容易踩的坑（已在文中修正）

- `find_class(...)` 返回的是 Chaquopy `JavaClass`，**没有反射方法**；
  取 Method 要用 `java.lang.Class.forName(...)`
- 菜单回调的 `context` 是 `java.util.HashMap`，**不能用 `.keys()`**；
  要用 `keySet().toArray()`
- `HookFilter` 的关键字参数是 `condition` / `index` / `clazz`
- `FilesController` 的 `FileInfo` / `Place` / 异常都是**嵌套成员**，模块级不存在

## exteragram-plugin-debug

**纯方法论**：只保留可复用的判据与流程，不含任何个人设备信息、私有插件名或本地路径。

主要内容：

- 离线改造插件的「生成脚本 + 校验脚本」两段式管线（含 5 类校验判据与 3 个易错点）
- adb 部署管线（chown/chmod/清 pyc/写 prefs 启用，含「装完 ≠ 生效」的两步机制）
- logcat 三条输出通道与时间窗陷阱；探针插件落盘法
- 插件设置的命名空间结构与读写坑
- 宿主反编译取证方法（access flag 判可覆写、反向引用查触发者）
- Chaquopy Java 互操作（集合不实现 Python 协议、未捕获异常被静默吞掉）
- 高频钩子性能（缓存 `Field`、TTL 缓存设置、先测再优化）
- UI 坐标定位、弹窗行漂移、软键盘顶起输入行
- Windows PowerShell 脚本的 BOM / splatting / 多设备坑
- 可选：手机 UI 自动化工具的能力边界与并发抓日志技巧

## 来源与许可

- **`exteragram-plugin-dev`** 源自开源项目
  [makarworld/exteragram-plugin-skill](https://github.com/makarworld/exteragram-plugin-skill)（MIT，
  `LICENSE` 随附），并按其自身声明的优先级（*live docs win*）做了真机校正与补充。
- **`exteragram-plugin-debug`** 为原创整理。
- **`exteragram-plugin-workflow`** 为原创整理。

## 注意事项

- 宿主类名、方法名、混淆情况**会随 exteraGram 版本变化**。文中涉及具体类名/方法名的地方，
  请以**你自己设备上的实测**为准。
- 部分操作需要 **root** 与应用的**开发者模式**。
- 修改 `shared_prefs`、删除插件文件等属敏感操作，**操作前请备份**。
