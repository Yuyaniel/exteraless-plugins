"""SKILL.md 里那份「现成规则」的正确性测试。

文档里的规则如果跑不通就是坑，所以这里把它们从 SKILL.md 里**抽出来**，
用插件自己的引擎跑一遍：
  - 每条正则必须能编译
  - 关键几条还要验证实际效果（含文档里声称"做不到"的那几件事）

跑法：
    python tests/test_rule_recipes.py
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_filter_engine import install_stubs, load_plugin_namespace  # noqa: E402

SKILL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills",
    "message-filter-rules",
    "SKILL.md",
)

# 表格形式： | 需求 | 类型 | `匹配内容` | ...
# 文档里类型有简写（词组 / 正则），这里都得认
ROW = re.compile(
    r"^\|\s*(?P<needle>[^|]+?)\s*\|\s*"
    r"(?P<mode>词组 / 子串|词组|字符集合|正则表达式|正则)\s*\|\s*"
    r"`(?P<pattern>[^`]+)`"
)

MODE_ITEMS = {"词组 / 子串": 0, "字符集合": 1, "正则表达式": 2}


def normalize_mode(raw):
    """把文档里的简写归一到插件里的类型名。"""
    if raw.startswith("词组"):
        return "词组 / 子串"
    if raw.startswith("正则"):
        return "正则表达式"
    return raw

PASSED = []
FAILED = []


def check(label, actual, expected):
    if actual == expected:
        PASSED.append(label)
    else:
        FAILED.append(
            "{}\n      期望: {!r}\n      实际: {!r}".format(label, expected, actual)
        )


def section(title):
    print("\n== {} ==".format(title))


def read_recipes():
    """从 SKILL.md 抽出现成规则。"""
    with open(SKILL_PATH, "r", encoding="utf-8") as handle:
        text = handle.read()
    out = []
    for line in text.splitlines():
        match = ROW.match(line)
        if not match:
            continue
        # 表格里为了不被竖线截断，正则中的 | 写成了 \|，读出来要还原
        pattern = match.group("pattern").replace("\\|", "|")
        out.append(
            (
                match.group("needle").strip(),
                normalize_mode(match.group("mode")),
                pattern,
            )
        )
    return out


def rule(pattern, mode, replacement=""):
    return {
        "id": "r1",
        "mode": mode,
        "pattern": pattern,
        "replacement": replacement,
        "case_sensitive": True,
        "scope": "",
        "target": 0,
    }


def run():
    install_stubs()
    ns = load_plugin_namespace()
    validate_pattern = ns["validate_pattern"]
    filter_message = ns["filter_message"]
    MODE_LITERAL = ns["MODE_LITERAL"]
    MODE_CHARS = ns["MODE_CHARS"]
    MODE_REGEX = ns["MODE_REGEX"]

    recipes = read_recipes()

    section("SKILL.md 规则抽查")
    check("抽到了规则", len(recipes) >= 18, True)

    section("每条正则都能编译")
    broken = []
    regex_count = 0
    for needle, mode, pattern in recipes:
        if mode != "正则表达式":
            continue
        regex_count += 1
        error = validate_pattern(MODE_REGEX, pattern)
        if error:
            broken.append("{}  ->  {}  ({})".format(pattern, error, needle))
    check("正则条数", regex_count >= 15, True)
    check("没有编译不过的正则", broken, [])

    section("文档给的正则确实能命中它声称的场景")
    # (需求关键词, 样本, 期望输出)
    cases = [
        ("去掉\"加微信\"三个字", "来 加微信 私聊", "来  私聊"),
        ("去掉任意链接", "看这个 https://a.b/c 很赞", "看这个  很赞"),
        ("去掉 @提及", "谢谢 @alice 帮忙", "谢谢  帮忙"),
        ("去掉手机号", "联系 13812345678 我", "联系  我"),
        ("去掉 t.me 链接", "来 t.me/abc 看看", "来  看看"),
        ("去掉邮箱", "发我 a.b@c.com 谢谢", "发我  谢谢"),
        ("去掉整行广告", "正常消息\n加微信领福利\n正常消息二", "正常消息\n正常消息二"),
        ("奖牌推广行", "榜单：\n🥇 第一名\n结束", "榜单：\n结束"),
    ]
    for needle, sample, expected in cases:
        found = [
            item
            for item in recipes
            if item[0] == needle or needle in item[0] or item[0] in needle
        ]
        if not found:
            check("能找到规则: {}".format(needle), False, True)
            continue
        _name, mode, pattern = found[0]
        actual = filter_message(sample, [rule(pattern, MODE_ITEMS[mode])])[0]
        check("命中: {}".format(needle), actual, expected)

    section("整合版奖牌推广行规则：正例与反例")
    medal_rows = [item for item in recipes if "奖牌推广行" in item[0]]
    check("能唯一定位到整合规则", len(medal_rows), 1)
    if medal_rows:
        _name, mode, medal_pattern = medal_rows[0]
        check("整合规则的类型是正则", mode, "正则表达式")
        check(
            "整合规则把两条判据并成一条（含外层分支）",
            "(?:" in medal_pattern and "|" in medal_pattern,
            True,
        )

        # 正例：奖牌行（分支 A）
        for sample in (
            "🥈【萝莉全国包养】高中生/学生/处女/萝莉/…",
            "🥇 冠军资源 上门服务",
            "🎖️m官方直营放心约💸同城萝莉上门约炮💸仅需88即可安排",
            "🎖️【萝莉上门｜最快半小时】【专注小萝莉｜品质有保障｜不嫩不要钱】",
            "  🥈缩进两格的广告",
        ):
            actual = filter_message(sample, [rule(medal_pattern, MODE_REGEX)])[0]
            check("奖牌行命中: {}".format(sample[:12]), actual, "（已过滤）")

        # 正例：emoji + 强推广词 + 无价目尾（分支 B）
        for sample in (
            "🔥上门服务 仅需88",
            "💸包养 直营 无定金",
            "📌定制 介绍费",
            "⭐ 榜一 直营 上门",
        ):
            actual = filter_message(sample, [rule(medal_pattern, MODE_REGEX)])[0]
            check("emoji+推广词命中: {}".format(sample[:12]), actual, "（已过滤）")

        # 反例：一条都不能误伤
        for sample in (
            "📢广州茶馆-在榜老师(新榜) 159k",
            "📢绅士该看的推特反差博主 155k",
            "热搜：夏鸣前 高要二中 李知恩 …",
            "👇点击按钮，筛选资源类型【第2页】",
            "👍这个我出 5k",
            "⭐ 已标记",
            "这个 🥇 是奖牌（不在行首）",
            "正常聊天：我明天上门找你",
        ):
            actual = filter_message(sample, [rule(medal_pattern, MODE_REGEX)])[0]
            check("不误伤: {}".format(sample[:12]), actual, sample)

    section("奖牌不在行首时的两条备用规则")
    anywhere = [item for item in recipes if "含奖牌" in item[0]]
    only_medal = [item for item in recipes if "只删掉奖牌" in item[0]]
    check("能找到「含奖牌的整行」", len(anywhere), 1)
    check("能找到「只删奖牌本身」", len(only_medal), 1)

    if anywhere:
        _n, _m, pat = anywhere[0]
        check(
            "行中间的奖牌也能删整行",
            filter_message("abc 🎖🥉🥇", [rule(pat, MODE_REGEX)])[0],
            "（已过滤）",
        )
        check(
            "只删命中那一行（不留空行）",
            filter_message("正常消息\nabc 🥇广告\n正常消息二", [rule(pat, MODE_REGEX)])[0],
            "正常消息\n正常消息二",
        )
    if only_medal:
        _n, _m, pat = only_medal[0]
        check(
            "只删奖牌本身、保留其余文字",
            filter_message("abc 🎖🥉🥇 def", [rule(pat, MODE_REGEX)])[0],
            "abc  def",
        )
        check(
            "没有奖牌就不动",
            filter_message("abc def", [rule(pat, MODE_REGEX)])[0],
            "abc def",
        )

    section("搜索 bot 结果清理：真实样本")
    bot_rows = [item for item in recipes if "搜索 bot" in item[0]]
    check("找到两条搜索 bot 规则", len(bot_rows), 2)
    if len(bot_rows) == 2:
        narrow = [row[2] for row in bot_rows if "只删奖牌行" in row[0]][0]
        keep_only = [row[2] for row in bot_rows if "只保留结果行" in row[0]][0]

        sample = "\n".join(
            (
                "🥇大学生包养【全球最大包养平台】真实可查 (https://t.me/+WTycnMpmlbFiODVl)",
                "🎖官方直营放心约大学生同城上门约炮仅需88即可安排 (https://t.me/+IC5kkN39NDYyMDk0)",
                "🏞体重：55_能不能无tao：_可_可不可以同居：否 (https://t.me/hongloubaoyang8/86327)",
                "🎬[14:59] 【19岁_爆乳大学生_林恩琪_遭土豪包养_3P视频曝光 (https://t.me/M3dTEmd3Kdt/1547)",
                "热搜 (https://t.me/jisou3bot?start=hotSearchGrow)：夏鸣前 高要二中",
            )
        )

        for name, pattern in (("删法", narrow), ("留法", keep_only)):
            out = filter_message(sample, [rule(pattern, MODE_REGEX)])[0]
            lines = [line for line in out.split("\n") if line.strip()]
            check("{}: 推广行和热搜行都删掉了".format(name), len(lines), 2)
            check("{}: 剩下的是两条结果行".format(name), lines[0].startswith("🏞"), True)
            check("{}: 含「包养」的结果行被保留".format(name), lines[1].startswith("🎬"), True)

        # 已知取舍：整合规则那条「emoji+强推广词」分支会误删含「包养」的结果行
        integrated = [item for item in recipes if "奖牌推广行" in item[0]][0][2]
        target = "🎬[14:59] 【19岁_爆乳大学生_林恩琪_遭土豪包养_3P视频曝光"
        check(
            "整合规则确实会误删这条结果行（所以搜索 bot 要用窄规则）",
            filter_message(target, [rule(integrated, MODE_REGEX)])[0],
            "（已过滤）",
        )
        check(
            "窄规则不误删这条结果行",
            filter_message(target, [rule(narrow, MODE_REGEX)])[0],
            target,
        )

    section("删整行不留空行（\\n? 的作用）")
    whole_line_rules = [item for item in recipes if "\\n?" in item[2]]
    check("整行删除类规则都带了 \\n?", len(whole_line_rules) >= 4, True)

    if len(bot_rows) == 2:
        narrow_nl = [row[2] for row in bot_rows if "只删奖牌行" in row[0]][0]
        sample = "\n".join(
            (
                "🥇广告一 (https://t.me/a)",
                "🥉广告二 (https://t.me/b)",
                "🏞结果一 (https://t.me/c)",
                "热搜：夏鸣前 高要二中",
                "🎬结果二 (https://t.me/d)",
            )
        )
        out = filter_message(sample, [rule(narrow_nl, MODE_REGEX)])[0]
        check("真删后一个空行都不留", [line for line in out.split("\n") if not line.strip()], [])
        check(
            "剩下的行原样保留",
            out,
            "🏞结果一 (https://t.me/c)\n🎬结果二 (https://t.me/d)",
        )

        # 链接安全开着时走「等长隐身」：长度守恒，而且同样不留空行
        blank_deleted = ns["blank_deleted"]
        u16_len = ns["_u16_len"]
        zwsp = ns["_ZWSP"]
        _text, removals, _prefix, _matched = filter_message(
            sample, [rule(narrow_nl, MODE_REGEX)]
        )
        cand = blank_deleted(sample, removals)
        check("等长隐身可用（整条没被删空）", cand is not None, True)
        if cand is not None:
            check("等长隐身 UTF-16 长度守恒", u16_len(cand), u16_len(sample))
            visible = [line.replace(zwsp, "") for line in cand.split("\n")]
            check(
                "等长隐身下也没有空行（换行被换成零宽字符）",
                [line for line in visible if not line.strip()],
                [],
            )
            check(
                "等长隐身下可见内容 == 真删结果",
                [line for line in visible if line.strip()],
                ["🏞结果一 (https://t.me/c)", "🎬结果二 (https://t.me/d)"],
            )

    section("文档里声称的四条限制确实成立")

    # 1. 替换为不支持反向引用
    actual = filter_message("aab", [rule("(.)", MODE_REGEX, replacement="\\1")])[0]
    check("反向引用被原样输出", actual, "\\1\\1\\1")

    # 2. 替换为插不进换行
    actual = filter_message("axb", [rule("x", MODE_REGEX, replacement="\\n")])[0]
    check("换行转义被原样输出", actual, "a\\nb")

    # 3. 字符集合模式里 \d 是字面量
    actual = filter_message("a1b", [rule("\\d", MODE_CHARS)])[0]
    check("字符集合不认 \\d，数字不会被删", actual, "a1b")
    actual = filter_message("a\\db", [rule("\\d", MODE_CHARS)])[0]
    check("字符集合只删字面的反斜杠和 d", actual, "ab")

    # 4. 词组模式不是正则
    actual = filter_message("a.*b", [rule(".*", MODE_LITERAL)])[0]
    check("词组模式下 .* 是字面量", actual, "ab")

    section("文档里的正则语法对照")
    check("\\x{FE0F} 在 Python 里非法", validate_pattern(MODE_REGEX, "\\x{FE0F}") is not None, True)
    check("\\uFE0F 在 Python 里合法", validate_pattern(MODE_REGEX, "\\uFE0F"), None)
    check("变长后顾非法", validate_pattern(MODE_REGEX, "(?<=a{1,3})b") is not None, True)
    check("定长后顾合法", validate_pattern(MODE_REGEX, "(?<=abc)b"), None)

    # 把文档里给的回避写法也验一遍：零宽字符要用正则模式的字符类
    zero_width = "[\u200b\u200c\u200d\ufeff]"
    check("零宽字符用正则能删掉", filter_message("a\u200bb", [rule(zero_width, MODE_REGEX)])[0], "ab")

    # 行尾 emoji 那条
    actual = filter_message("文字🎉", [rule("[\\U0001F300-\\U0001FAFF\\u2600-\\u27BF]+$", MODE_REGEX)])[0]
    check("行尾 emoji 被删掉", actual, "文字")


def main():
    run()
    print("\n" + "=" * 60)
    print("通过 {} 项，失败 {} 项".format(len(PASSED), len(FAILED)))
    if FAILED:
        for item in FAILED:
            print("  ✗ {}".format(item))
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
