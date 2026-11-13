"""HTML into an allowlisted native tree: never execute export markup."""
from html.parser import HTMLParser

TAGS = {"p","div","span","h1","h2","h3","h4","h5","h6","ul","ol","li","table","thead","tbody","tfoot","tr","td","th","blockquote","pre","code","strong","b","em","i","u","s","sub","sup","br","hr"}
BLOCKED = {"script","style","iframe","object","embed","form","input","button"}


class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = []
        self.stack = [("root", self.root)]
        self.blocked = 0
        self.warnings = []
    def handle_starttag(self, tag, attrs):
        if tag in BLOCKED:
            self.warnings.append({"code":"excluded_active_html","tag":tag})
            if tag not in {"input","embed"}: self.blocked += 1
            return
        if self.blocked: return
        attrs = dict(attrs)
        if tag == "img":
            self.stack[-1][1].append({"type":"image","src":attrs.get("src",""),"alt":attrs.get("alt","")})
            return
        if tag == "a":
            node = {"type":"link","href":attrs.get("href",""),"children":[]}
        elif tag in {"center","o:p","textarea"}:
            node={"type":"element","tag":"pre" if tag=="textarea" else "div","children":[]}
        elif tag in TAGS or tag == "font":
            node = {"type":"element","tag":tag if tag != "font" else ("code" if "monospace" in attrs.get("style","") else "span"),"children":[]}
        else:
            self.warnings.append({"code":"unsupported_html_tag","tag":tag})
            node = {"type":"element","tag":"span","children":[]}
        self.stack[-1][1].append(node)
        if tag not in {"br","hr","meta","link","source","wbr"}:
            self.stack.append((tag,node["children"]))
    def handle_endtag(self, tag):
        if tag in BLOCKED:
            self.blocked = max(0, self.blocked-1)
            return
        if self.blocked: return
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i][0] == tag:
                self.stack = self.stack[:i]
                break
    def handle_data(self, text):
        if not self.blocked and text:
            self.stack[-1][1].append({"type":"text","text":text})


def parse_html(raw):
    parser = Parser()
    parser.feed(raw)
    return parser.root, parser.warnings
