# exteraless-plugins

exteraless / exteraGram 客户端插件，外加一套配套的 AI Agent 技能包。

**宿主基线**：exteraless `12.10.6`（`com.exteraless.app`，exteraGram 系）· 插件 SDK `1.4.5.7` · Python 3.11（Chaquopy）
插件声明的兼容范围：`__app_version__ = ">=12.5.1"` · `__sdk_version__ = ">=1.4.5.0"`

> 两个插件都只改**你自己客户端**上的显示与行为——不动服务端数据，也不影响别人的客户端。

---

## 插件

| 目录 | 插件 | 一句话 |
|---|---|---|
| [`MessageFilter/`](MessageFilter/) | **Message Filter** `v1.1.0` | 按规则**移除消息里匹配的部分**（词组 / 字符集合 / 正则），只删匹配内容、保留其余；支持按会话生效、多条规则按优先级执行、过滤后加标记 |
| [`AutoDownload/`](AutoDownload/) | **Auto Download** `v1.1.0` | 按**会话 + 网络类型**决定媒体是否自动下载；不自己调下载接口，而是改写宿主 `canDownloadMedia` 的返回值 |

### Message Filter

```
今天促销 加微信xxx 速来   →   今天促销  速来
```

- 三种匹配方式：**词组 / 子串**、**字符集合**（逐字符删）、**正则表达式**（Python `re`）
- 只删匹配的部分，也可以**替换**（`12345` → `****`）
- 多条规则按列表顺序执行，逐条启用/禁用，可分「仅收 / 仅发 / 收+发」
- 可**只在某个群/频道生效**：在那个会话的右上角菜单里直接加规则
- **格式不串味**：改写文本后修正加粗/链接偏移；拿不到格式实体时改用「等长隐身删除」，保证链接不串行
- 历史消息也过滤（挂 `getHistory` / `getMessages` / `search` 等请求钩子）

细节见 [`MessageFilter/README.md`](MessageFilter/README.md) 与 [`MessageFilter/docs.md`](MessageFilter/docs.md)。

### Auto Download

- 按媒体类型分别开关：图片 / 视频 / GIF / 语音音频 / 文件
- WiFi 与移动数据各一套规则
- 可按会话单独配置，没配过的走默认规则；会话一旦配置过就以会话自己为准
- 实现方式是 hook 宿主 `DownloadController.canDownloadMedia`，**只改一个决策位**，
  排队 / 分组 / 续传全部仍走宿主自己的管线

细节见 [`AutoDownload/README.md`](AutoDownload/README.md) 与 [`AutoDownload/docs.md`](AutoDownload/docs.md)。

---

## 技能包

[`skills/`](skills/) 下是三个给 AI Agent 用的技能（Skill）文档：

| 目录 | 作用 | 规模 |
|---|---|---|
| [`exteragram-plugin-dev/`](skills/exteragram-plugin-dev/) | **开发**：BasePlugin SDK、事件 hook、设置页、菜单项、Class Proxy、Elyx、日志、依赖管理 | `SKILL.md` + 17 个 `reference/` + 4 个 `examples/` |
| [`exteragram-plugin-debug/`](skills/exteragram-plugin-debug/) | **排障**：adb 部署管线、logcat 三通道、宿主反编译取证、Chaquopy 互操作陷阱、性能优化 | 单文件 `SKILL.md` |
| [`exteragram-plugin-workflow/`](skills/exteragram-plugin-workflow/) | **从零搭工作流**：6 阶段施工图，每阶段给命令与验收判据 | 单文件 `SKILL.md` |

用法：支持技能目录的助手（Claude Skills / DSH / 其他 agent 框架）把目录整个放进技能目录即可；
不支持的直接把 `SKILL.md` 贴进对话当上下文，`reference/` 按需追加。

---

## 插件怎么装

1. exteraGram → 设置 → 插件 → 打开**插件引擎**；插件信息页打开**开发者模式**
2. 把 `*.plugin` 复制进设备的插件目录，**并改名为 `*.py`**
   （`.plugin` 是仓库里的源码后缀，设备上加载器只认 `.py`；文件名必须等于 `__id__`）
3. 在插件列表里启用，**重启应用**

```bash
adb push MessageFilter/message_filter.plugin /data/local/tmp/message_filter.py
adb shell "su -c 'cp /data/local/tmp/message_filter.py /data/data/com.exteraless.app/files/plugins/message_filter.py'"
adb shell "su -c 'chown <uid>:<uid> /data/data/com.exteraless.app/files/plugins/message_filter.py'"
adb shell "su -c 'chmod 600 /data/data/com.exteraless.app/files/plugins/message_filter.py'"
adb shell "su -c 'rm -f /data/data/com.exteraless.app/files/plugins/__pycache__/message_filter.cpython-311.pyc'"
adb shell "am force-stop com.exteraless.app"
```

`<uid>` 换成应用 uid：`adb shell "su -c 'stat -c %u /data/data/com.exteraless.app'"`

---

## 开发与测试

`.plugin` **就是 Python 源码**，没有构建步骤，直接改它。三套测试都用桩模块替换 SDK 后
**exec 插件源码本身**，所以测的是真代码、不是副本。

```bash
# Message Filter —— 83 + 140 + 64 项
python MessageFilter/tests/test_filter_engine.py
python MessageFilter/tests/test_plugin_adapter.py
python MessageFilter/tests/test_rule_recipes.py

# Auto Download
python AutoDownload/tests/test_decision_engine.py
python AutoDownload/tests/test_plugin_adapter.py
```

需要 Python 3.11+（桌面测试不依赖 Chaquopy）。

---

## 许可

- 插件与 `exteragram-plugin-debug`、`exteragram-plugin-workflow`：MIT
- `exteragram-plugin-dev`：源自 [makarworld/exteragram-plugin-skill](https://github.com/makarworld/exteragram-plugin-skill)（MIT，`LICENSE` 随附），
  按其自身声明的优先级（*live docs win*）做了真机校正与补充

## 注意

宿主类名、方法名、混淆情况**会随 exteraGram 版本变化**。文中涉及具体类名/方法名的地方，
请以**你自己设备上的实测**为准。部分操作需要 **root** 与应用的**开发者模式**。
