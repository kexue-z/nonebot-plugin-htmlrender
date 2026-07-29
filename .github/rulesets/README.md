# Repository Rulesets

本目录保存 GitHub Ruleset 的可审计导入文件，但 GitHub 不会因为文件位于
`.github/rulesets/` 而自动应用它们。远端启用顺序、环境保护和验证方式见
[仓库治理与保护](../../docs/maintainers/quality/repository-governance.md)。

修改 workflow 汇总 job 名称时，必须同步更新 `protect-master.json` 中的
`required_status_checks`，并在远端观察到新 context 后再更新已启用的 Ruleset。
