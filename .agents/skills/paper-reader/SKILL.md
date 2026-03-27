---
name: paper-reader
description: >
  用于阅读、总结、解释、比较学术论文，尤其是 AI / ML / LLM / Agent papers。
  When the user asks to read, summarize, explain, inspect, compare, or discuss a paper from a local PDF path,
  arXiv ID/URL, title, or screenshot, use this skill. 默认用中文输出；第一次出现的重要术语给中英对照；
  优先展示原文图表或裁图，而不是只复述摘要。
---

# Paper Reader

## 目标

把论文讲明白，而不是机械复述摘要。默认交付物有两份：

- 对话里的中文解读。
- 当前项目目录下的论文工作目录，至少包含 `paper.pdf`、`summary.md` 和 `assets/`。

工作目录命名默认采用 `时间戳_论文标题_arxivid`，例如 `20260327-153045-123_Attention_Is_All_You_Need_1706.03762`。如果输入是本地 PDF 且确实拿不到 arXiv ID，后缀用 `no-arxiv`。

风格应该像一个懂行的同事在帮用户拆论文：

- 先说结论，再讲背景、方法、证据和局限。
- 尽量说人话，避免空泛套话。
- 有原文图表就优先用图表，尤其是方法图、主结果图和关键表格。
- 关键术语第一次出现时用「中文（English）」或「中文（English, 缩写）」。

生成最终回答前，必须阅读 [`references/output-style.md`](references/output-style.md)，并按其中的结构和写作要求组织内容。

## 工作流

### 1. 先解析论文来源

- 用户给本地 PDF：把 PDF 作为内容真源。
- 只要用户是在让你完整读一篇论文、总结一篇论文，或做需要落盘的论文分析，第一步必须运行 `scripts/prepare_paper_workspace.py`。不要先单独运行 `scripts/arxiv_api.py` 或 `scripts/fetch_paper_pdf.py`。
- 用户给 arXiv ID、arXiv URL、DOI 风格 arXiv 标识或标题时，`scripts/prepare_paper_workspace.py` 会自己完成解析、命名目录、下载 PDF 和初始化 `summary.md`。
- `scripts/arxiv_api.py` 现在只用于两类场景：用户明确只想看元数据/候选结果；或者你在排查解析失败、查询语法和限流问题。
- 不要默认把 PDF 下载到 `.paper-reader/papers/` 再手工搬运；优先让 `prepare_paper_workspace.py` 直接把 PDF 落到目标目录里。
- 只有在需要查询语法、字段或限流规则时，才读 `references/arxiv-api.md`。

### 1.5 完整读论文时的强制动作

- 运行 `scripts/prepare_paper_workspace.py` 后，记录它返回的 `workspace.directory`、`workspace.summary_markdown`、`workspace.assets_directory` 和 `workspace.pdf_path`。
- 后续所有截图、裁图和其他资源都写到 `workspace.assets_directory`，不要散落到 `.paper-reader/` 或其他临时目录。
- 在最终回复用户之前，必须把完整总结写入 `workspace.summary_markdown`，不能只保留脚本创建的空白骨架。
- 如果因为网络沙箱导致 shell 里的 arXiv 请求失败，可以改用允许的联网方式继续拿元数据或 PDF；但即便如此，最后也必须回到这个工作目录里，把 `summary.md` 和 `assets/` 补齐。

### 2. 优先拿到原文图表

- 讲方法图、架构图、表格、算法框、结果图之前，优先准备原文截图。
- 默认使用 `scripts/render_pdf_pages.py` 渲染相关页；输出目录优先指向当前论文工作目录下的 `assets/`。如果只需要某个 figure/table，就用 `--crop` 输出裁好的图表，不要默认贴整页。
- 只有当页面整体布局本身有意义时，才展示整页。
- 原文已经有好图时，不要自己重画；只有原文没有对应可视化且用户确实需要时，才考虑自绘示意图。

### 3. 以证据为中心阅读

- 优先读：标题、摘要、引言、方法、主图、主表、实验、结论。
- 长论文要有策略地抽样：开头几页、核心方法页、关键实验页、结论页；并明确哪些部分没有细读。
- 结论尽量落到页码、章节、Figure、Table。
- 论文没直接回答的问题，要明确标注“以下是我的理解/推断”。

### 4. 默认中文回答

- 默认在对话中输出中文解读，同时把完整总结写入当前论文工作目录里的 `summary.md`。
- `summary.md` 里所有截图、裁图和其他资源都放在同级 `assets/` 子目录，并使用相对路径引用，例如 `![方法图](assets/method-figure.png)`。
- 如果用户只是追问一个细节，而且没有要求完整落盘，可以只回答该问题；如果用户要“读一下这篇论文”，就先建工作目录，再按 `references/output-style.md` 的完整结构输出到对话和 `summary.md`。
- 如果用户要求比较多篇论文，先分别解析每篇，再比较问题设定、核心方法、实验结果和权衡。

## 快速用法

只在需要单独查看元数据或排障时，才直接解析 arXiv：

```bash
python3 .agents/skills/paper-reader/scripts/arxiv_api.py "2401.12345"
python3 .agents/skills/paper-reader/scripts/arxiv_api.py "https://arxiv.org/abs/2401.12345"
python3 .agents/skills/paper-reader/scripts/arxiv_api.py "Attention Is All You Need" --max-results 5
```

初始化论文工作目录并下载 PDF：

```bash
python3 .agents/skills/paper-reader/scripts/prepare_paper_workspace.py "2401.12345"
python3 .agents/skills/paper-reader/scripts/prepare_paper_workspace.py "https://arxiv.org/abs/2401.12345"
python3 .agents/skills/paper-reader/scripts/prepare_paper_workspace.py "Attention Is All You Need"
```

只想单独下载 PDF 时：

```bash
python3 .agents/skills/paper-reader/scripts/fetch_paper_pdf.py "2401.12345"
python3 .agents/skills/paper-reader/scripts/fetch_paper_pdf.py "Attention Is All You Need"
```

渲染整页到工作目录的 `assets/`：

```bash
python3 .agents/skills/paper-reader/scripts/render_pdf_pages.py /path/to/paper-workspace/paper.pdf --pages 1,5,8 --output-dir /path/to/paper-workspace/assets
```

裁出某个 figure / table：

```bash
python3 .agents/skills/paper-reader/scripts/render_pdf_pages.py /path/to/paper-workspace/paper.pdf --pages 5 --crop 0.08,0.04,0.90,0.23 --output-dir /path/to/paper-workspace/assets
```

## 证据规则

- 优先使用原文 PDF 的图表和文字，不靠印象复述。
- 引用数字时给出处，至少落到页码、Figure、Table 或章节。
- 默认少量引用、以转述为主。
- 如果只拿到了 arXiv 元数据或摘要页，没有读到全文，要明确说清楚。

## 资源

- `scripts/arxiv_api.py`: 解析 arXiv ID、URL、标题或原始查询，返回结构化 JSON。
- `scripts/prepare_paper_workspace.py`: 创建 `时间戳_标题_arxivid` 论文工作目录，生成 `summary.md` 和 `assets/`，并把 PDF 放到 `paper.pdf`。
- `scripts/fetch_paper_pdf.py`: 解析 arXiv 目标并下载 PDF，默认写到 `.paper-reader/papers/`，会复用已有有效文件并校验 PDF 头。
- `scripts/render_pdf_pages.py`: 渲染 PDF 页面，并可直接裁出 figure / table。
- `references/output-style.md`: 论文解读的默认输出结构、语气和取舍标准。
- `references/arxiv-api.md`: arXiv API 查询语法和字段说明。
- `references/troubleshooting.md`: TLS、Poppler、裁图等排障说明。
