#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""轻量语法高亮器（零第三方依赖，纯标准库实现）。

输出：<span style="color:#xxxxxx">...</span> 片段，可直接嵌入微信公众号文章
（微信不支持 class / <style> 标签，所以只能用内联 style）。

设计要点：
1. 先对整个代码块做 token 切分，再逐个 token 转义，避免转义后的实体（如 &amp;）
   被词法规则误匹配。
2. 每个 token 内部若含换行，会被拆成多段输出，保证「没有任何 <span> 跨行」，
   这样上层可以按 \\n 安全地切行来做行号等处理。
"""

import html
import re

# ---------------------------------------------------------------------------
# 代码配色主题
# ---------------------------------------------------------------------------

CODE_THEMES = {
    "one-dark": {
        "label": "One Dark（深色·默认）",
        "bg": "#282c34",
        "bar_bg": "#21252b",
        "bar_fg": "#8b949e",
        "fg": "#abb2bf",
        "comment": "#5c6370",
        "string": "#98c379",
        "number": "#d19a66",
        "keyword": "#c678dd",
        "builtin": "#56b6c2",
        "function": "#61afef",
        "tag": "#e06c75",
        "attr": "#d19a66",
        "operator": "#abb2bf",
        "gutter": "#5c6370",
        "border": "#3a3f4b",
    },
    "monokai": {
        "label": "Monokai（深色·高对比）",
        "bg": "#272822",
        "bar_bg": "#1e1f1c",
        "bar_fg": "#8a8a72",
        "fg": "#f8f8f2",
        "comment": "#75715e",
        "string": "#e6db74",
        "number": "#ae81ff",
        "keyword": "#f92672",
        "builtin": "#66d9ef",
        "function": "#a6e22e",
        "tag": "#f92672",
        "attr": "#a6e22e",
        "operator": "#f92672",
        "gutter": "#75715e",
        "border": "#3e3d32",
    },
    "dracula": {
        "label": "Dracula（深色·柔和）",
        "bg": "#282a36",
        "bar_bg": "#21222c",
        "bar_fg": "#8b8fa3",
        "fg": "#f8f8f2",
        "comment": "#6272a4",
        "string": "#f1fa8c",
        "number": "#bd93f9",
        "keyword": "#ff79c6",
        "builtin": "#8be9fd",
        "function": "#50fa7b",
        "tag": "#ff79c6",
        "attr": "#50fa7b",
        "operator": "#ff79c6",
        "gutter": "#6272a4",
        "border": "#44475a",
    },
    "github-light": {
        "label": "GitHub Light（浅色）",
        "bg": "#f6f8fa",
        "bar_bg": "#eceff3",
        "bar_fg": "#6a737d",
        "fg": "#24292e",
        "comment": "#6a737d",
        "string": "#032f62",
        "number": "#005cc5",
        "keyword": "#d73a49",
        "builtin": "#6f42c1",
        "function": "#6f42c1",
        "tag": "#22863a",
        "attr": "#6f42c1",
        "operator": "#24292e",
        "gutter": "#b0b5bb",
        "border": "#e1e4e8",
    },
    "xcode": {
        "label": "Xcode（浅色·高对比）",
        "bg": "#fbfbfd",
        "bar_bg": "#f2f2f7",
        "bar_fg": "#7c7c80",
        "fg": "#3b3b3b",
        "comment": "#007400",
        "string": "#d12f1b",
        "number": "#272ad8",
        "keyword": "#ad3da4",
        "builtin": "#3900a0",
        "function": "#4b21b0",
        "tag": "#ad3da4",
        "attr": "#4b21b0",
        "operator": "#3b3b3b",
        "gutter": "#b8b8bb",
        "border": "#e6e6e6",
    },
}

DEFAULT_CODE_THEME = "one-dark"

# ---------------------------------------------------------------------------
# 语言词法定义
# ---------------------------------------------------------------------------

_C_COMMENT = [r"//[^\n]*", r"/\*[\s\S]*?\*/"]
_HASH_COMMENT = [r"#[^\n]*"]
_DQ_SQ = [r'"(?:\\.|[^"\\\n])*"', r"'(?:\\.|[^'\\\n])*'"]
_PY_STRING = [
    r"[rbfuRBFU]{0,3}\"\"\"[\s\S]*?\"\"\"",
    r"[rbfuRBFU]{0,3}'''[\s\S]*?'''",
] + _DQ_SQ

_KEYWORDS = {
    "python": (
        r"\b(?:def|class|return|if|elif|else|for|while|import|from|as|try|except|finally"
        r"|raise|with|pass|break|continue|lambda|yield|global|nonlocal|assert|del"
        r"|async|await|in|is|not|and|or)\b"
    ),
    "javascript": (
        r"\b(?:var|let|const|function|return|if|else|for|while|do|switch|case|default|break"
        r"|continue|new|delete|typeof|instanceof|class|extends|super|this|try|catch|finally"
        r"|throw|async|await|yield|import|export|from|of|in|static|get|set)\b"
    ),
    "typescript": (
        r"\b(?:var|let|const|function|return|if|else|for|while|do|switch|case|default|break"
        r"|continue|new|delete|typeof|instanceof|class|extends|implements|interface|enum"
        r"|super|this|try|catch|finally|throw|async|await|yield|import|export|from|of|in"
        r"|static|get|set|public|private|protected|readonly|declare|namespace|type)\b"
    ),
    "java": (
        r"\b(?:public|private|protected|class|interface|enum|extends|implements|static|final"
        r"|void|return|if|else|for|while|do|switch|case|default|break|continue|new|try"
        r"|catch|finally|throw|throws|import|package|this|super|abstract|synchronized"
        r"|volatile|transient|native|instanceof|assert)\b"
    ),
    "kotlin": (
        r"\b(?:fun|val|var|class|object|interface|companion|data|sealed|when|is|in|return"
        r"|if|else|for|while|do|try|catch|finally|throw|import|package|override|suspend"
        r"|private|public|protected|internal|open|abstract|final|const|lateinit|this|super)\b"
    ),
    "swift": (
        r"\b(?:func|var|let|class|struct|enum|protocol|extension|import|return|if|else|for"
        r"|in|while|guard|switch|case|default|break|continue|throw|throws|try|catch|do|defer"
        r"|self|init|deinit|private|public|internal|fileprivate|open|static|override|lazy"
        r"|weak|unowned|where|as|is|super|associatedtype|typealias)\b"
    ),
    "go": (
        r"\b(?:func|package|import|var|const|type|struct|interface|map|chan|go|defer|select"
        r"|case|default|return|if|else|for|range|switch|break|continue|goto|fallthrough)\b"
    ),
    "rust": (
        r"\b(?:fn|let|mut|const|static|struct|enum|impl|trait|pub|use|mod|crate|as|return|if"
        r"|else|for|while|loop|in|match|move|ref|where|unsafe|dyn|async|await|self|Self"
        r"|break|continue|type|box|dyn|super)\b"
    ),
    "c": (
        r"\b(?:return|if|else|for|while|do|switch|case|default|break|continue|goto|struct"
        r"|union|enum|typedef|static|const|volatile|extern|register|sizeof|include|define"
        r"|ifdef|ifndef|endif|unsigned|signed|void|int|char|float|double|long|short|auto)\b"
    ),
    "cpp": (
        r"\b(?:return|if|else|for|while|do|switch|case|default|break|continue|goto|struct"
        r"|class|union|enum|typedef|static|const|volatile|extern|sizeof|template|typename"
        r"|namespace|using|public|private|protected|virtual|override|inline|new|delete|try"
        r"|catch|throw|noexcept|constexpr|auto|nullptr|true|false|this|operator|inline)\b"
    ),
    "csharp": (
        r"\b(?:class|interface|struct|enum|namespace|using|public|private|protected|internal"
        r"|static|readonly|const|void|return|if|else|for|foreach|while|do|switch|case|default"
        r"|break|continue|new|try|catch|finally|throw|async|await|var|get|set|override|virtual"
        r"|abstract|sealed|this|base|delegate|event|params|out|ref|in|is|as|lock|checked)\b"
    ),
    "php": (
        r"\b(?:function|class|interface|trait|namespace|use|public|private|protected|static"
        r"|return|if|else|elseif|for|foreach|while|do|switch|case|default|break|continue"
        r"|new|try|catch|finally|throw|echo|empty|isset|unset|array|extends|implements|const"
        r"|global|require|include|abstract|final|yield|clone|instanceof|this)\b"
    ),
    "ruby": (
        r"\b(?:def|class|module|end|return|if|elsif|else|unless|case|when|while|until|for|do"
        r"|begin|rescue|ensure|raise|yield|require|include|extend|attr_accessor|self|nil"
        r"|true|false|lambda|proc|then|redo|retry|super|alias|defined\?)\b"
    ),
    "sql": (
        r"(?i)\b(?:select|from|where|insert|into|values|update|set|delete|create|table|view"
        r"|index|drop|alter|add|primary|key|foreign|references|join|left|right|inner|outer"
        r"|full|cross|on|as|group|by|order|having|limit|offset|distinct|union|all|case|when"
        r"|then|else|end|and|or|not|in|exists|between|like|asc|desc|with|replace|truncate"
        r"|explain|begin|commit|rollback|grant|revoke|count|sum|avg|max|min|coalesce|cast)\b"
    ),
    "bash": (
        r"\b(?:if|then|else|elif|fi|for|in|do|done|while|until|case|esac|function|return"
        r"|exit|local|export|readonly|shift|trap|set|unset|break|continue|select|time)\b"
    ),
    "yaml": r"\b(?:true|false|null|yes|no|on|off)\b",
    "json": r"\b(?:true|false|null)\b",
    "dockerfile": (
        r"(?i)\b(?:FROM|RUN|CMD|LABEL|MAINTAINER|EXPOSE|ENV|ADD|COPY|ENTRYPOINT|VOLUME|USER"
        r"|WORKDIR|ARG|ONBUILD|STOPSIGNAL|HEALTHCHECK|SHELL)\b"
    ),
    "nginx": (
        r"\b(?:server|location|listen|server_name|root|index|proxy_pass|upstream|include"
        r"|access_log|error_log|ssl_certificate|ssl_certificate_key|return|rewrite|if|try_files"
        r"|client_max_body_size|keepalive_timeout|gzip|resolver)\b"
    ),
}

PY_BUILTINS = (
    r"\b(?:print|len|range|open|enumerate|zip|map|filter|list|dict|set|tuple|str|int|float"
    r"|bool|bytes|abs|all|any|min|max|sum|sorted|reversed|isinstance|hasattr|getattr|setattr"
    r"|super|type|id|repr|format|round|input|next|iter|dir|vars|callable|staticmethod"
    r"|classmethod|property|Exception|BaseException|ValueError|TypeError|KeyError|IndexError"
    r"|StopIteration|True|False|None|self)\b"
)
JS_BUILTINS = (
    r"\b(?:console|window|document|Math|JSON|Object|Array|String|Number|Boolean|Date|Promise"
    r"|Map|Set|Symbol|RegExp|Error|require|module|exports|process|globalThis|true|false|null"
    r"|undefined|NaN|Infinity)\b"
)
JAVA_BUILTINS = (
    r"\b(?:String|Integer|Long|Double|Float|Boolean|Character|Byte|Short|System|Math|Object"
    r"|List|ArrayList|Map|HashMap|Set|HashSet|Optional|Stream|true|false|null|void)\b"
)
GO_BUILTINS = (
    r"\b(?:string|int|int8|int16|int32|int64|uint|uint8|uint16|uint32|uint64|float32|float64"
    r"|bool|byte|rune|error|interface\{\}|nil|true|false|iota|make|new|len|cap|append|copy"
    r"|print|println|panic|recover|fmt|err|ctx)\b"
)
RUST_BUILTINS = (
    r"\b(?:i8|i16|i32|i64|i128|u8|u16|u32|u64|u128|f32|f64|bool|char|str|String|Vec|Option"
    r"|Result|Box|Arc|Rc|RefCell|Mutex|RwLock|HashMap|HashSet|BTreeMap|Some|None|Ok|Err"
    r"|true|false)\b"
)
C_BUILTINS = (
    r"\b(?:int|char|float|double|long|short|unsigned|signed|void|size_t|ssize_t|uint8_t"
    r"|uint16_t|uint32_t|uint64_t|int8_t|int16_t|int32_t|int64_t|bool|true|false|NULL|printf"
    r"|scanf|malloc|free|calloc|realloc|memcpy|memset|strlen|strcpy|strcmp|exit|std|nullptr)\b"
)
SQL_BUILTINS = r"(?i)\b(?:int|bigint|varchar|text|timestamp|date|numeric|decimal|boolean|uuid|jsonb|serial)\b"
BASH_BUILTINS = (
    r"\b(?:echo|cd|ls|pwd|mkdir|rm|cp|mv|cat|grep|sed|awk|find|curl|wget|tar|zip|unzip|chmod"
    r"|chown|kill|ps|top|df|du|ssh|scp|docker|kubectl|git|brew|apt|yum|npm|yarn|pip|python3"
    r"|python|make|gcc|sudo|systemctl|journalctl|which|env|export|source|read|test|printf)\b"
)


def _lang_spec(lang: str) -> dict:
    """返回某语言的词法规则描述。未知语言返回空规则（纯文本色）。"""
    c_comment = ("comment", _C_COMMENT)
    hash_comment = ("comment", _HASH_COMMENT)

    if lang in ("python", "py"):
        return {
            "comment": _HASH_COMMENT,
            "string": _PY_STRING,
            "keyword": _KEYWORDS["python"],
            "builtin": PY_BUILTINS,
        }
    if lang in ("javascript", "js", "jsx", "node", "mjs"):
        return {
            "comment": _C_COMMENT,
            "string": _DQ_SQ + [r"`(?:\\.|[^`\\])*`"],
            "keyword": _KEYWORDS["javascript"],
            "builtin": JS_BUILTINS,
        }
    if lang in ("typescript", "ts", "tsx"):
        return {
            "comment": _C_COMMENT,
            "string": _DQ_SQ + [r"`(?:\\.|[^`\\])*`"],
            "keyword": _KEYWORDS["typescript"],
            "builtin": JS_BUILTINS,
        }
    if lang == "java":
        return dict(comment=_C_COMMENT, string=_DQ_SQ, **{
            "keyword": _KEYWORDS["java"], "builtin": JAVA_BUILTINS})
    if lang in ("kotlin", "kt"):
        return dict(comment=_C_COMMENT, string=_DQ_SQ, **{
            "keyword": _KEYWORDS["kotlin"], "builtin": JAVA_BUILTINS})
    if lang == "swift":
        return dict(comment=_C_COMMENT, string=_DQ_SQ, **{
            "keyword": _KEYWORDS["swift"], "builtin": None})
    if lang in ("go", "golang"):
        return dict(comment=_C_COMMENT, string=_DQ_SQ + [r"`[^`]*`"], **{
            "keyword": _KEYWORDS["go"], "builtin": GO_BUILTINS})
    if lang == "rust":
        return dict(comment=_C_COMMENT, string=_DQ_SQ, **{
            "keyword": _KEYWORDS["rust"], "builtin": RUST_BUILTINS})
    if lang == "c":
        return dict(comment=_C_COMMENT, string=_DQ_SQ, **{
            "keyword": _KEYWORDS["c"], "builtin": C_BUILTINS})
    if lang in ("cpp", "c++", "cc", "cxx"):
        return dict(comment=_C_COMMENT, string=_DQ_SQ, **{
            "keyword": _KEYWORDS["cpp"], "builtin": C_BUILTINS})
    if lang in ("csharp", "c#", "cs"):
        return dict(comment=_C_COMMENT, string=_DQ_SQ, **{
            "keyword": _KEYWORDS["csharp"], "builtin": None})
    if lang == "php":
        return dict(comment=_C_COMMENT + [r"#[^\n]*"], string=_DQ_SQ, **{
            "keyword": _KEYWORDS["php"], "builtin": None})
    if lang == "ruby":
        return dict(comment=_HASH_COMMENT, string=_DQ_SQ, **{
            "keyword": _KEYWORDS["ruby"], "builtin": None})
    if lang == "sql":
        return dict(comment=[r"--[^\n]*", r"/\*[\s\S]*?\*/"], string=_DQ_SQ, **{
            "keyword": _KEYWORDS["sql"], "builtin": SQL_BUILTINS})
    if lang in ("bash", "sh", "shell", "zsh", "console", "shell-session"):
        return dict(comment=_HASH_COMMENT, string=_DQ_SQ, **{
            "keyword": _KEYWORDS["bash"], "builtin": BASH_BUILTINS,
            "extra": [("builtin", r"\$\w+|\$\{[^}]*\}|(?<![\w$])[a-zA-Z_]\w*(?==)")]})
    if lang in ("yaml", "yml"):
        return dict(comment=_HASH_COMMENT, string=_DQ_SQ, **{
            "keyword": _KEYWORDS["yaml"],
            "builtin": r"\b(?:true|false|null|yes|no)\b",
            "extra": [("attr", r"(?<![\w:\"'/.\-])[\w.\-/@]+(?=\s*:(?!//))")]})
    if lang == "json":
        return {"string": _DQ_SQ, "keyword": _KEYWORDS["json"],
                "extra": [("attr", r'"(?:\\.|[^"\\])*"(?=\s*:)')]}
    if lang in ("dockerfile", "docker"):
        return dict(comment=_HASH_COMMENT, string=_DQ_SQ, **{
            "keyword": _KEYWORDS["dockerfile"], "builtin": None})
    if lang == "nginx":
        return dict(comment=_HASH_COMMENT, string=_DQ_SQ, **{
            "keyword": _KEYWORDS["nginx"], "builtin": None})
    if lang in ("css", "scss", "less"):
        return {
            "comment": _C_COMMENT,
            "string": _DQ_SQ,
            "extra": [
                ("tag", r"[.#@]?[-\w]+(?=[ \t]*\{)"),
                ("attr", r"[-\w]+(?=[ \t]*:)"),
                ("builtin", r"#[0-9a-fA-F]{3,8}\b"),
            ],
        }
    if lang in ("html", "xml", "vue", "svg", "jsx-html", "markdown", "md"):
        return {
            "comment": [r"<!--[\s\S]*?-->"],
            "string": _DQ_SQ,
            "extra": [
                ("tag", r"</?[a-zA-Z][\w:-]*|/?>"),
                ("attr", r"[a-zA-Z_:][\w:.-]*(?=\s*=)"),
            ],
        }
    if lang == "diff":
        return {
            "extra": [
                ("string", r"^\+[^\n]*"),
                ("keyword", r"^-[^\n]*"),
                ("builtin", r"^@@[^\n]*"),
                ("comment", r"^[^+\-@][^\n]*"),
            ],
        }
    return {}


def _build_rules(lang: str):
    spec = _lang_spec(lang)
    rules = []
    for name in ("comment", "string"):
        for pat in spec.get(name, []):
            rules.append((name, re.compile(pat, re.M if pat.startswith(("^", r"^")) else 0)))
    extra = spec.get("extra") or []
    for item in extra:
        name, pat = item if isinstance(item, (tuple, list)) else (item[0], item[1])
        flags = re.M if isinstance(pat, str) and pat.startswith(("^", r"^")) else 0
        rules.append((name, re.compile(pat, flags)))
    kw = spec.get("keyword")
    if kw:
        rules.append(("keyword", re.compile(kw, re.I if lang in ("sql", "nginx", "dockerfile") else 0)))
    bi = spec.get("builtin")
    if bi:
        rules.append(("builtin", re.compile(bi, re.I if lang == "sql" else 0)))
    rules.append(("number", re.compile(r"\b(?:0[xX][\da-fA-F]+|0[bB][01]+|\d+\.?\d*(?:[eE][+-]?\d+)?)\b")))
    rules.append(("function", re.compile(r"\b[A-Za-z_]\w*(?=\s*\()")))
    rules.append(("operator", re.compile(r"[+\-*/%=<>!&|^~?@]+")))
    return rules


_RULE_CACHE = {}

# 常见别名 -> 规范语言名
ALIASES = {
    "python": "python", "py": "python", "python3": "python",
    "javascript": "javascript", "js": "javascript", "jsx": "javascript", "node": "javascript",
    "typescript": "typescript", "ts": "typescript", "tsx": "typescript",
    "java": "java", "go": "go", "golang": "go", "rust": "rust", "rs": "rust",
    "c": "c", "cpp": "cpp", "c++": "cpp", "c#": "csharp", "csharp": "csharp", "cs": "csharp",
    "php": "php", "ruby": "ruby", "rb": "ruby", "sql": "sql", "swift": "swift",
    "kotlin": "kotlin", "bash": "bash", "sh": "bash", "shell": "bash", "zsh": "bash",
    "yaml": "yaml", "yml": "yaml", "json": "json", "html": "html", "xml": "xml",
    "css": "css", "scss": "css", "less": "css", "vue": "html", "dockerfile": "dockerfile",
    "docker": "dockerfile", "nginx": "nginx", "diff": "diff", "md": "text", "markdown": "text",
}


def normalize_lang(raw: str) -> str:
    if not raw:
        return "text"
    key = raw.strip().lower()
    key = key.replace("objective-c", "objc")
    return ALIASES.get(key, key)


LANG_LABEL = {
    "python": "Python", "javascript": "JavaScript", "typescript": "TypeScript",
    "java": "Java", "go": "Go", "rust": "Rust", "c": "C", "cpp": "C++",
    "csharp": "C#", "php": "PHP", "ruby": "Ruby", "sql": "SQL", "swift": "Swift",
    "kotlin": "Kotlin", "bash": "Shell", "yaml": "YAML", "json": "JSON",
    "html": "HTML", "xml": "XML", "css": "CSS", "dockerfile": "Dockerfile",
    "nginx": "Nginx", "diff": "Diff", "text": "Text",
}


def highlight_lines(code: str, lang: str = "text", theme: str = DEFAULT_CODE_THEME,
                    line_numbers: bool = False):
    """返回逐行的 HTML（list[str]，不含外层标签），供渲染器按模式组装。"""
    theme_map = CODE_THEMES.get(theme, CODE_THEMES[DEFAULT_CODE_THEME])
    lang = normalize_lang(lang)

    if lang == "text" or lang not in _lang_spec_all():
        return _split_plain(html.escape(code), theme_map, line_numbers)

    rules = _RULE_CACHE.get(lang)
    if rules is None:
        rules = _build_rules(lang)
        _RULE_CACHE[lang] = rules

    parts = []
    pos = 0
    n = len(code)
    while pos < n:
        ch = code[pos]
        if ch in " \t":
            nxt = pos
            while nxt < n and code[nxt] in " \t":
                nxt += 1
            parts.append(("none", code[pos:nxt]))
            pos = nxt
            continue
        matched = None
        for name, rx in rules:
            m = rx.match(code, pos)
            if m and m.end() > m.start():
                matched = (name, m)
                break
        if matched is None:
            # 找不到规则：收集到下一个可匹配位置之前的连续字符
            end = pos + 1
            parts.append(("none", code[pos:end]))
            pos = end
            continue
        name, m = matched
        parts.append((name, m.group(0)))
        pos = m.end()

    out = []
    for name, text in parts:
        color = theme_map.get(name) or (theme_map["fg"] if name != "none" else None)
        for i, seg in enumerate(text.split("\n")):
            if i:
                out.append("\n")
            if not seg:
                continue
            esc = html.escape(seg, quote=False)
            if esc != seg or " " in seg or "\t" in seg:
                esc = esc.replace(" ", "&nbsp;").replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
            if color:
                out.append('<span style="color:%s">%s</span>' % (color, esc))
            else:
                out.append(esc)
    return _finalize("".join(out).split("\n"), theme_map, line_numbers)


def _finalize(lines, theme_map, line_numbers):
    """去掉末尾多余空行，并按需给每行加行号前缀。"""
    while lines and re.sub(r"<[^>]*>", "", lines[-1]).replace("&nbsp;", " ").strip() == "":
        lines.pop()
    if not lines:
        lines = [""]
    if not line_numbers:
        return lines
    gutter = theme_map["gutter"]
    width = len(str(len(lines)))
    res = []
    for idx, line in enumerate(lines, 1):
        res.append(
            '<span style="color:%s;opacity:.55;padding-right:10px;'
            '-webkit-user-select:none;user-select:none">%s</span>%s'
            % (gutter, str(idx).rjust(width), line))
    return res


def _split_plain(escaped_code, theme_map, line_numbers):
    lines = [l.replace(" ", "&nbsp;").replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
             for l in escaped_code.split("\n")]
    return _finalize(lines, theme_map, line_numbers)


def highlight(code: str, lang: str = "text", theme: str = DEFAULT_CODE_THEME,
              mode: str = "block", line_numbers: bool = False) -> str:
    """把源码高亮成 HTML 片段（不含外层 <pre>）。

    mode="block" —— 每行包一层 <section>（推荐）。
    mode="pre"   —— 行之间用 \\n 分隔，依赖容器的 white-space:pre 换行（易被清洗，不推荐）。

    ★ 为什么必须是 <section> 而不是 <span style="display:block">★

    公众号后台在保存/预览时会重新解析正文并清洗内联样式。实测：容器 <section> 上的
    background-color / border-radius 都能活下来，但写在 <span> 上的 display 会被丢掉。
    一旦 display:block 丢失，span 退回行内元素，而相邻 span 之间连一个换行符都没有，
    所有代码行就会**无缝挤成一行**（"EOFvm.swappiness = 1" 这种），比样式丢失更糟。

    <section> 的块级是**标签本身的语义**，不依赖任何 CSS —— 就算 style 被整条洗掉，
    每行依然各占一行。所以分行必须交给结构化标签，绝不能再依赖 display。
    """
    lines = highlight_lines(code, lang, theme, line_numbers)
    if mode == "pre":
        return "\n".join(lines)
    res = []
    for line in lines:
        if line.strip():
            res.append("<section style=\"margin:0;padding:0\">%s</section>" % line)
        else:
            # 空行：给个 &nbsp; 撑出正常行高，样式被洗掉也不会塌成 0 高度
            res.append('<section style="margin:0;padding:0;min-height:1.65em">&nbsp;</section>')
    return "".join(res)


def _lang_spec_all():
    return set(ALIASES.values()) | {"diff"}


def supported_languages():
    return sorted(set(ALIASES.keys()) | {"text"})


def supported_code_themes():
    return sorted(CODE_THEMES.keys())


if __name__ == "__main__":
    import sys
    sample = sys.stdin.read()
    print(highlight(sample, "python", "one-dark", line_numbers=False))
