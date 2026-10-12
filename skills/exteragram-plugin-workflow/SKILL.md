---
name: exteragram-plugin-workflow
description: >-
  从零搭建 exteraGram 插件开发的 Agent 工作流（6 阶段施工图，含命令与验收判据）。
  Use when the user wants to 搭建/初始化/部署 exteraGram 插件开发环境或工作流，
  建立 SDK 事实层、部署管线、可观测性、知识层与纪律约束，或询问
  "怎么开始写 exteraGram 插件 / 怎么搭一套插件开发环境 / 环境勘察怎么做 /
  部署管线怎么建 / 怎么抓插件日志 / 新对话怎么快速接手项目"。
  与 exteragram-plugin-dev（API 手册）、exteragram-plugin-debug（排障手册）配套：
  本文档只讲"怎么把工作流搭起来"，不讲 API 细节。
  触发词：exteraGram 工作流、插件开发环境、搭建开发环境、SDK 事实层、
  部署管线、logcat 可观测性、知识层、交接文档。
---

# 用 Agent 搭建 exteraGram 插件工作流

> 本技能正文即下方完整施工文档。配套技能：
> `exteragram-plugin-dev`（开发 API 手册）、`exteragram-plugin-debug`（排障方法论）。
> 事实权威顺序：**设备运行时 > 本地 SDK 副本 > 官方文档**。

---

# 用 Agent 搭建 exteraGram 插件开发工作流

> **这是什么**：一份**搭建方法**文档 —— 把一套可用的 exteraGram 插件开发工作流从零搭起来，
> 交给 AI Agent（Claude / DSH / Cursor 等具备 shell 能力的 agent）执行。
>
> **不是**插件 API 手册（那部分见同目录的 `exteragram-plugin-dev/`），
> **也不是**排障手册（见 `exteragram-plugin-debug/`）。
>
> **怎么用**：把本文档连同两个技能目录一起交给 agent，说「按这份文档帮我把工作流搭起来」。
> 每个阶段都给了**命令**与**验收判据**，agent 可以自查是否真的做对了。

---

## 〇、核心设计原则（先看这 5 条，决定了后面所有结构）

这套工作流的价值不在"脚本多"，而在**约束 agent 不乱猜**。五条原则：

| # | 原则 | 为什么 |
|---|---|---|
| 1 | **事实分层，且运行时 > 本地副本 > 文档** | 本地提取的 SDK 副本会落后于设备实际加载的版本；文档会落后于两者。搞错权威顺序会得到**系统性错误答案** |
| 2 | **单一事实源** | 同一批 API 事实散落在多处、各自过时，是反复出错的根源。只允许一个文件写事实，其余只引用 |
| 3 | **探针优于猜测** | API 形态不确定时，先写 5 分钟探针在真机确认，再写正式代码 |
| 4 | **判据化** | 每个结论都要能复现：写命令、写对照表、写"看到 X 就是 Y" |
| 5 | **纪律前置** | 把"禁止编造 API / 禁止猜包名"写成文档里的硬规则，而不是靠 agent 自觉 |

---

## 一、总览：6 个阶段与产物

| 阶段 | 做什么 | 产物 | 验收判据 |
|---|---|---|---|
| 0 | 前置条件 | — | 设备在线 + 应用侧开关已开 |
| 1 | **环境勘察** | `knowledge/env-facts.md` | 包名/root/ABI 全部**实测**得出 |
| 2 | **建立 SDK 事实层** | `sdk/` + 版本对照 | 拿到设备**运行时**的 SDK 版本 |
| 3 | **搭部署管线** | `tools/` 脚本 | 能一条命令完成"部署→启用→重启→抓日志" |
| 4 | **可观测性** | `knowledge/logcat-guide.md` + 探针模板 | 能稳定抓到插件启动日志 |
| 5 | **知识层与纪律** | `knowledge/` 全套 + 交接文档 | 新对话读 3 个文件即可接手 |
| 6 | **验证与迭代** | 最小插件 + 踩坑回填 | 最小插件跑通闭环 |

> **建议顺序**：1 → 2 → 3 → 4 → 5 → 6。
> 但 **5（知识层骨架）可以在 1 之后就建**，这样后续每步的结论都有地方落盘。

---

## 二、阶段 0：前置条件

### 人工准备（agent 做不了的部分）

1. **一台已 root 的 Android 设备**（Magisk 等），USB 调试已开
   - 需要 root 是因为插件目录与 `shared_prefs` 都在 `/data/data/<pkg>/` 下
2. **PC 上装好 `adb`**，并确认在 PATH 中（或记下绝对路径）
3. **目标应用已安装**，且完成两件事：
   - 设置里开启 **插件引擎**
   - 插件信息页开启 **开发者模式**
4. **逆向工具（可选）**：JDK + jadx / apktool —— 只在需要确认宿主类名/方法时才用

### 验收判据

```bash
adb devices              # 设备处于 device 状态（不是 unauthorized / offline）
adb shell "su -c id"     # 输出 uid=0 → root 可用
```

---

## 三、阶段 1：环境勘察

**目标**：把"我以为的环境"变成"实测的环境"。

### 要采集的事实

| 项目 | 命令 | 备注 |
|---|---|---|
| 设备序列号 | `adb devices -l` | 多设备时后续命令都要 `-s` |
| 型号 / 品牌 | `adb shell getprop ro.product.model` / `ro.product.brand` | |
| Android 版本 | `getprop ro.build.version.release` / `ro.build.version.sdk` | |
| CPU ABI | `getprop ro.product.cpu.abi` / `ro.product.abilist` | 决定取哪个架构的 SDK |
| root 状态 | `su -c id` | 看 `uid=0` 与 SELinux 上下文 |
| **应用包名** | `adb shell pm list packages \| grep -i <关键词>` | **禁止猜**，必须实测 |
| 应用版本 | `adb shell dumpsys package <pkg> \| grep -E "versionName\|versionCode"` | |
| 应用安装路径 | `dumpsys package <pkg> \| grep codePath` | 后面 pull APK 要用 |
| 工具链 | `where adb` / `java -version` / `jadx --version` … | 记下**绝对路径**，别依赖 PATH |

### ⚠️ 这一步最容易犯的错

**搜索范围不全导致误报"工具缺失"**。
真实案例：第一轮环境检查只扫了 `C:\` 下的几个目录，没扫其他盘，
于是误报 `adb / java / jadx` **全部缺失**，差点白装一遍。

⇒ **规则**：扫描工具链时，**把机器上所有可能的数据盘都纳入范围**；
报"缺失"之前先确认搜索路径完整。

### 另一个常见坑：同机存在多个变体应用

设备上可能同时装了目标应用的**另一个变体包**（不同包名）。
⇒ **所有脚本必须显式指定包名**，禁止模糊匹配。

### 产物：`knowledge/env-facts.md`

结构建议：

```markdown
# 环境事实（实测值）
> 最后核实：YYYY-MM-DD
> API 事实不写在这里 —— 只写进 sdk-version-diff.md（单一事实源）

## 一、目标设备
| 项目 | 值 | 来源 |
|---|---|---|
| 序列号 | <device-serial> | adb devices -l |
| Android 版本 | ... | getprop |
| CPU ABI | ... | getprop |
| Root | ✅/❌ | su -c id |

## 二、目标应用
| 项目 | 值 |
|---|---|
| package name | <pkg>（实测，禁止猜） |
| 版本 | ...（versionCode ...） |

## 三、SDK        ← 阶段 2 填
## 四、工具链
## 五、环境限制（沙箱/权限等，附替代方案）
```

### 验收判据

- 包名是 `pm list packages` 的输出，**不是**从文档抄的
- 每个值都标了来源命令
- 没有"推测"字样混在实测值里

---

## 四、阶段 2：建立 SDK 事实层

### ★ 关键认知：APK 内嵌的 SDK ≠ 设备运行时加载的 SDK

这是整套工作流**最重要的一个坑**：

- APK 里会带一份 SDK（通常在 `assets/<something>/sdk-<abi>.zip` + 一个 `v.txt` 版本文件）
- 但**应用安装后会自行更新**设备上的 SDK 目录（如 `files/chaquopy/plugins-sdk/`）
- 两者**版本可能不同，模块清单也可能不同**

**真实案例**：APK 内嵌 `1.4.5.5`，设备运行时是 `1.4.5.7`；
`log_utils` 模块**只存在于后者**。若按 APK 内嵌副本做二进制字符串搜索，会得出
「该模块不存在」的**错误结论**。

⇒ **规则**：判断运行时行为，**必须内省设备**，不能读 APK 内嵌资源。

### 提取步骤

```bash
# 1. 找到设备上的 SDK 目录（从插件运行时的 sys.path 或 chaquopy 目录入手）
adb -s <serial> shell "su -c 'ls /data/data/<pkg>/files/chaquopy/'"

# 2. 打包并拉取（目录较大，先压缩）
adb -s <serial> shell "su -c 'cd /data/data/<pkg>/files/chaquopy && \
    tar czf /data/local/tmp/sdk.tgz plugins-sdk && chmod 644 /data/local/tmp/sdk.tgz'"
adb -s <serial> pull /data/local/tmp/sdk.tgz ./sdk.tgz

# 3. 本地解压到 sdk/
tar xzf sdk.tgz && mv plugins-sdk sdk/

# 4. 确认版本
cat sdk/v.txt            # 形如 1.4.5.7|0
```

### 版本二次确认（更可靠）

版本文件可能过时，**运行时读到的才是权威**。写一个探针插件读：

```python
import _sdk_version
emit("sdk __version__ = %r" % _sdk_version.__version__)   # 如 '1.4.5.7'
emit("sdk version     = %r" % (_sdk_version.version,))    # 如 (1, 4, 5, 7)
```

（探针的部署方式见阶段 3、4。）

### 产物：`knowledge/sdk-version-diff.md`

这是**单一事实源**，结构建议：

```markdown
# SDK 版本差异清单 ★ 单一事实源
> 其他文档只引用本文件，不复制内容。

## 一、版本对照（已确认）
| 来源 | 版本 | 性质 | 核查方式 |
|---|---|---|---|
| 设备运行时（最高权威） | ... | 事实层 | 探针读 _sdk_version |
| 设备 SDK 文件 | ... | 事实层 | v.txt |
| 本地 sdk/ 副本 | ... | 事实层 | sdk/v.txt |
| APK 内嵌 SDK | ... | 历史事实 | assets/... |
| 官方文档 | ... | 文档层 | 网页 |
| 已装 skill | ... | 文档层 | SKILL.md |

## 二、模块清单与覆盖情况
## 三、真机实测 API 事实（★ 核心）
## 四、待实测填充区
```

### 验收判据

- 拿到了**设备运行时**的版本号（不是只读 `v.txt`）
- 本地 `sdk/` 与设备 `plugins-sdk/` **一致**（md5 抽查）
- 文档里区分了"事实层"与"文档层"

---

## 五、阶段 3：搭部署管线

### 部署的 8 个步骤（缺一不可）

```
1. 写插件代码（本地）
2. 静态检查（语法 + metadata 必须是单个字面量）
3. push 到 /data/local/tmp      ← ⚠️ 源路径必须纯 ASCII
4. su -c cp 到插件目录
5. su -c chown <app_uid>:<app_uid>    ← 不 chown 应用读不了
6. su -c chmod 600
7. su -c rm -rf __pycache__            ← 不删可能加载旧字节码
8. 启用 + 重启
```

### ★★ 第 8 步的真相：「装完 ≠ 生效」

**实测结论**：

| 场景 | 是否需要重启 |
|---|---|
| **新插件首次注册**（从未启用过） | ✅ **需要**（写启用标记 + 重启，两步都要） |
| **已注册插件**的启用/禁用切换 | ❌ 不需要，立即生效 |

判据：`shared_prefs/plugin_settings.xml` 里是否有 `plugin_enabled_<id>` 条目。
应用**启动时不扫描新增插件文件** —— 不写这个条目，插件永远不加载。

### 启用可以全自动（不需要 UI 操作）

```
force-stop → pull XML → 在 </map> 前插入一行 → push 回
（chown <app_uid>、chmod 600）→ am start
```

**顺序不可颠倒**：应用运行中改 prefs 会被内存副本覆盖。

> **风险提示**：改 `shared_prefs` 属敏感操作（**改前备份**）；
> XML 格式错误会让**所有**插件开关失效；文件里若有 `had_crash` / `crashed_plugin_id`
> 需一并清理，否则插件会被立刻禁用。

### 建议做的 5 个脚本

| 脚本 | 职责 | 关键点 |
|---|---|---|
| `adb_check` | 检查设备 / root / 应用 / 插件目录 | 多设备时自动选用或报错要求指定 |
| `install_plugin` | 部署（重命名 `.py`、chown、chmod、清缓存、备份同名文件） | push 源路径必须 ASCII |
| `logcat_plugin` | 抓插件日志 | 覆盖三条 TAG 通道（见阶段 4） |
| `restart_app` | 重启应用并等待加载 | **用 `am start`，禁用 `monkey`** |
| `test_plugin` | 串联：检查 → 部署 → 重启 → 抓日志 → 分析 | 失败时给出排查清单 |

### ⚠️ 启动应用：禁止用 `monkey`

`monkey -c LAUNCHER 1` 会**把系统「自动旋转」打开**（用户会以为手机自己改了设置）。
用 `am start`：

```bash
adb -s <serial> shell am start -n <pkg>/org.telegram.ui.LaunchActivity
```

判据：`adb shell settings get system accelerometer_rotation`（1=开，0=关）。

**"不用 monkey 会不会变慢？"实测反而更快**（`am start` 约 0.13s，`monkey` 约 0.80s），
而且 monkey 唯一的好处（不用硬编码 Activity 名）可以用动态解析拿到：

```bash
adb -s <serial> shell cmd package resolve-activity --brief -c android.intent.category.LAUNCHER <pkg>
```

### ⚠️ 如果脚本用 PowerShell

四条硬规则：

1. **文件必须带 UTF-8 BOM** —— PS 5.1 按 ANSI/GBK 读无 BOM 文件，中文乱码会**破坏语法解析**
2. **用 `$ErrorActionPreference = 'Continue'`** —— adb 把进度写 stderr，`Stop` 会误判为异常
3. **不能用 `& $数组` 调用** —— 用 splatting（`& $exe @args`）
4. **多设备必须显式 `-Serial`**

> **BOM 的隐蔽性**：不只是"新建文件"要注意 —— **任何编辑工具改写 .ps1 后都可能丢 BOM**。
> 改完务必复查（读前 3 字节是否为 `EF BB BF`），并跑一次语法自检：
> ```powershell
> $errs = $null
> [System.Management.Automation.Language.Parser]::ParseFile("x.ps1", [ref]$null, [ref]$errs) | Out-Null
> if ($errs) { $errs | ForEach-Object { $_.Message } } else { "OK" }
> ```

### 验收判据

- 一条命令能把插件从本地推到设备并让它**真的加载**（日志里有 `on_plugin_load`）
- 卸载后菜单项 id 变化（证明旧实例被清理）
- 启动应用**不改变** `accelerometer_rotation`

---

## 六、阶段 4：可观测性

### 三条日志通道（都要覆盖）

| 调用 | logcat TAG | 说明 |
|---|---|---|
| `self.log(...)` | `[PyObject]` | legacy，固定 debug 级别，**无法按插件过滤** |
| `android_utils.log(...)` | `[Python]` | 带 `[getModule]` 前缀 |
| **`self.logger.info(...)`** | **`plugin.<插件id>`** | 推荐；带 `[文件:函数:行号]` 前缀，可 `logcat -s plugin.<id>` |

> 不同 SDK 版本可能**只有前两条**。用 `_sdk_version` 判断，或直接看日志里有没有第三条。

**抓取命令**：

```bash
adb -s <serial> logcat [PyObject]:D [PyMethodHook]:E [Python]:D plugin:V *:S
```

### ⚠️ 两个必须知道的陷阱

1. **启动日志有时间窗** —— 实测启动十几秒内还有插件日志，到 18 秒左右就**归零**。
   慢一步就会误判「插件没加载」。要长时间观察就用后台 `logcat -v time > file`。
2. **插件日志不落盘** —— 应用目录下的 `logs/` 是宿主自己的日志，
   插件 `log()` **不会**写进去；应用内也**没有**日志查看器。
   要落盘只能插件自己写文件。

### ★ 探针插件：结果写文件，不要只打日志

调试插件**自身**（尤其是加载阶段）时，日志会被静默吞掉，所以：

```python
import sys
OUT = "/data/data/<pkg>/files/_probe_out.txt"

def emit(s):
    with open(OUT, "a", encoding="utf-8") as f:     # 追加写
        f.write(str(s) + "\n")

def probe(label, fn):
    try:
        emit("%-40s => %r" % (label, fn()))
    except Exception as e:                          # 必须 except Exception
        emit("%-40s !! %s: %s" % (label, type(e).__name__, e))

# 关键：在 import base_plugin 之前先 emit 一条
# 这样即使 import 阶段就抛异常，文件里也已经留下痕迹
emit("probe start python=%s" % sys.version)
```

**要点**：

1. 每条探测独立 `try/except Exception`，每个分支都落盘
2. `dir(obj)` 一次列出 Java 对象全部方法，**不要靠猜**
3. **源文件路径必须纯 ASCII** —— 含中文的路径会让 `adb push` **静默挂起**（无报错、无进度）
4. 探针要能回答具体问题：某个模块能不能 import、某个 API 的参数名是什么、某个对象是什么类型

### ⚠️ 未捕获异常会被宿主静默吞掉

插件回调里抛出的**未捕获异常，在 logcat 中完全看不到**。
⇒ 排查时**一律用 `except Exception`**，并**在每个分支都打日志**，
否则会陷入"代码明明执行了但什么都没发生"的死胡同。

### 产物：`knowledge/logcat-guide.md`

内容：三条通道对照表、过滤命令、时间窗陷阱、日志不落盘的事实、探针模板。

### 验收判据

- 能稳定抓到**启动阶段**的插件日志（不是靠反复重试碰运气）
- 探针文件在插件 import 失败时**仍有内容**

---

## 七、阶段 5：知识层与纪律

### 目录结构建议

```
<workspace>/
├── README.md                工作区总入口（含阶段进度）
├── knowledge/               ★ agent 优先读这里
│   ├── README.md                 架构 + 权威性顺序
│   ├── env-facts.md              环境事实（阶段 1）
│   ├── sdk-version-diff.md       ★ 单一事实源（阶段 2）
│   ├── logcat-guide.md           日志速查（阶段 4）
│   └── plugin-deploy-mechanism.md 部署机制（阶段 3）
├── tools/                   ADB 自动化脚本（阶段 3）
├── sdk/                     设备实际 SDK（阶段 2）
├── plugin/                  插件开发工作区（新插件放这里）
├── examples/                插件样本索引
├── docs/                    官方文档 / 技能索引
└── reverse/                 逆向产物与结论
```

### 四层知识架构（权威性从高到低）

| 层级 | 位置 | 角色 |
|---|---|---|
| **L1 运行时事实** | 设备内省（探针 + `dir()`） | **最高**，冲突时以此为准 |
| **L2 设备 SDK 文件** | `sdk/` | 设备实际安装的 SDK 二进制 |
| **L3 差异层 / 单一事实源** | `knowledge/sdk-version-diff.md` | 记录 L1/L2 与文档层的落差 |
| **L4 文档层** | 官方文档 / 已装 skill | 参考，可能滞后 |

**冲突裁决**：L1 > L2 > L3 > L4。

> **二进制字符串搜索要排在 L2 之下**：编译产物的字符串池只含编译进该模块的字面量，
> 且版本错配时会给出**系统性错误答案**。只在 L1/L2 都拿不到时才用。

### 单一事实源规则

> **API 事实只写进 `sdk-version-diff.md`。**
> 交接文档、README、技能文档一律只**引用**、不复制。

理由：同一批事实散落多处后，各自过时程度不同，会出现"三份文档三种说法"。

### 纪律清单（写进文档，而不是靠自觉）

```
禁止编造 API / class / method
禁止猜 package name / Hook 参数
禁止把第三方客户端（NagramX 等）的 API 当成目标应用的插件 API
禁止没有日志就盲目修改
禁止一次修改大量无关代码
禁止用 monkey 启动应用（会打开系统「自动旋转」）
禁止用二进制字符串搜索代替真机内省
禁止把 API 事实复制到多处（只写进单一事实源）
```

**信息不足时**：停止 → 说明缺什么 → 要求获取对应日志 / SDK / APK 信息。

### 交接机制：让新对话 5 分钟接手

写一个 `新对话交接.md`，开头放一段**可直接复制**的提示词：

```
我在 <workspace> 做 exteraGram 插件开发，环境已经就绪。
请先读这几个文件了解上下文：
  1. knowledge/README.md           （知识层总览 + 权威性顺序）
  2. knowledge/sdk-version-diff.md （★ 单一事实源：真机实测 API 事实）
  3. knowledge/env-facts.md        （环境事实，实测值）
  4. knowledge/plugin-deploy-mechanism.md （部署生效机制）
  5. knowledge/logcat-guide.md     （日志 TAG 与过滤）
工具：tools/ 下已有实测通过的 ADB 脚本。
设备：<型号> / Android <版本>，<应用> <版本> / SDK <版本>，序列号 <serial>。
我的需求是：<在这里写插件需求>
```

这份交接文档里**只放**：环境速查、已验证的事实摘要、工具清单、目录结构、纪律。
**不放**：完整 API 手册（那是技能文档的事）。

### 验收判据

- 新开一个对话，只给它这份交接文档，它能正确说出"API 事实以哪个文件为准"
- 任一事实在仓库里**只有一个权威出处**

---

## 八、阶段 6：验证与迭代

### 用最小插件跑通闭环

写一个**只做一件事**的插件（例如改写一条外发消息），验证：

```
写插件 → 静态检查 → 部署 → 启用 → 重启 → 抓日志 → 看到预期行为
```

这一步跑通，说明**部署管线 + 可观测性**都对了。

### 用探针验证 API（写正式代码之前）

**流程**：

```
需求 → ★ 探针在真机确认 API 形态 → 写正式插件 → 静态检查 → 部署 → 启用 → 重启
     → 抓日志 → 分析 → 最小修改 → 重复
```

真实教训：直接照文档写 `find_class(...).getDeclaredMethod(...)`，
在真机上抛 `AttributeError`（`find_class` 返回的对象**没有反射方法**，
要用 `java.lang.Class.forName(...)`）。先花几分钟写探针，能避免整轮返工。

### 踩坑要回填

每解决一个问题，把它写进**单一事实源**（或对应 knowledge 文件），格式：

| 现象 | 说法/预期 | 实际行为 | 证据 | 影响面 | 状态 |
|---|---|---|---|---|---|

**只写有证据的**。推测要显式标注"未验证"。

---

## 九、踩坑总表（按阶段，搭的时候照这个清单自查）

| 阶段 | 坑 | 症状 | 对策 |
|---|---|---|---|
| 1 | 工具链搜索范围不全 | 误报"工具缺失" | 扫描所有数据盘再下结论 |
| 1 | 同机多个变体包 | 命令打到别的应用上 | 所有脚本显式指定包名 |
| 2 | **APK 内嵌 SDK ≠ 运行时 SDK** | 按内嵌副本得出错误结论 | 必须内省设备 |
| 3 | `monkey` 启动 | 系统「自动旋转」被打开 | 用 `am start` |
| 3 | **push 源路径含中文** | push **静默挂起** | 源路径必须纯 ASCII |
| 3 | 忘了 chown | 应用读不到插件 | 复制后立即 chown 回应用 uid |
| 3 | 忘了删 `__pycache__` | 加载旧字节码 | 部署流程固定带上 |
| 3 | **装完 ≠ 生效** | 日志零痕迹 | 写 `plugin_enabled_<id>` + 重启 |
| 3 | PS 脚本丢 BOM | 语法解析报莫名错误 | 复查前 3 字节 + 语法自检 |
| 3 | PS `Stop` 语义 | adb 进度被当异常 | 统一用 `Continue` |
| 4 | 日志时间窗 | 慢一步就"没有日志" | 后台持续抓 / 先开流再启动 |
| 4 | 未捕获异常被吞 | "什么都没发生" | 一律 `except Exception` + 分支打日志 |
| 4 | 只 grep 一个 TAG | 漏掉新式日志 | 覆盖三条通道 |
| 5 | 事实写多处 | 文档互相矛盾 | 单一事实源 + 只引用不复制 |
| 6 | 照文档写 API | 真机报错 | 先探针后编码 |

---

## 十、怎么把这套东西交给 agent

### 一次性搭建

```
把本文档 + exteragram-plugin-dev/ + exteragram-plugin-debug/ 三个东西交给 agent，
说：
  「按《用 Agent 搭建 exteraGram 插件开发工作流》在工作区 <path> 把工作流搭起来。
   我的设备已连接，应用已装好并开了插件引擎 + 开发者模式。
   每完成一个阶段，把产物写到对应位置，并跑一遍该阶段的验收判据。」
```

### 日常使用

搭好之后，日常只需要：

```
读 <workspace>/新对话交接.md，然后：<你的需求>
```

agent 会按交接文档的指引去读知识层，并按纪律工作。

### 给 agent 的三条硬约束（可复制到你的 AGENTS.md）

```
1. API 事实只认 knowledge/sdk-version-diff.md；拿不准就写探针在真机验证。
2. 禁止猜 package name / Hook 参数 / 类名方法名。
3. 改完 .ps1 必须复查 UTF-8 BOM 并跑语法自检。
```

---

## 十一、配套文件

同目录下：

| 文件 | 用途 |
|---|---|
| `exteragram-plugin-dev/` | 插件**开发**技能：SDK API、hook、设置页、Class Proxy、Elyx、日志… |
| `exteragram-plugin-debug/` | 插件**排障**技能：部署管线、日志三通道、反编译取证、性能陷阱… |
| `README.md` | 技能包的入口说明 |

建议把两个技能装进你的 agent 技能目录，本文档作为"搭建说明书"单独保存。
