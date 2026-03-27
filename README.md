# paper-reader

这是 `paper-reader` 的 Codex 版 skill 仓库。

仓库里只保存 skill 本身的定义、脚本和参考资料；单篇论文的运行产物留在本地工作区，但不进入 Git。

## 仓库内容

- `AGENTS.md`
  当前工作区的默认行为约定。
- `.agents/skills/paper-reader/SKILL.md`
  `paper-reader` 的主说明。具体工作流、输出风格和使用规则都以这里为准。
- `.agents/skills/paper-reader/scripts/`
  与论文处理相关的脚本，包括 arXiv 解析、PDF 下载、工作目录初始化、页面渲染与裁图。
- `.agents/skills/paper-reader/references/`
  补充文档，例如输出风格、arXiv API 说明和排障说明。
- `.agents/skills/paper-reader/agents/openai.yaml`
  agent 元数据与默认提示。

## Git 边界

会提交：

- skill 定义
- 脚本
- 参考文档
- 仓库级说明

不会提交：

- `__pycache__/` 和 `*.pyc`
- `.DS_Store`
- 每篇论文生成的时间戳工作目录

典型的论文工作目录会包含：

```text
<paper-workspace>/
├── paper.pdf
├── summary.md
└── assets/
```

## 维护原则

- README 只解释这个仓库是什么、放什么。
- 具体怎么读论文、怎么产出总结，放在 `SKILL.md`。
- 如果实现变了，优先更新 `scripts/` 和 `SKILL.md`，不要把细节重复写进 README。
