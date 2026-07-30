---
title: 发布流程
description: 版本 PR、tag 校验、PyPI 与 GitHub Release 发布及失败恢复
icon: lucide/package-check
status: new
tags:
  - Project
  - Release
  - PyPI
---

# 发布流程

正式发布以一个经过 review 的版本 PR 开始，以不可移动的 `v<version>` tag 为源代码锚点。PyPI、GitHub Release 和版本化文档是三条相互关联但独立执行、独立恢复的链路。

项目仍处于 pre-1.0。版本号采用 PEP 440 并保持单调递增，但不宣称 `0.x.y` 的 patch 位遵循 SemVer 的兼容含义。发布决策应明确区分“已发布公共 API”“当前分支尚未发布接口”和“必须修正的不可靠默认行为”，并为默认行为变化提供迁移说明。

## 发布前提

版本 PR 必须：

1. 将 `pyproject.toml` 中的项目版本更新为目标版本，并通过 `uv` 更新锁文件；
1. 完成与该版本相关的实现、测试、迁移说明和使用指南；
1. 通过 [Pull Request 生命周期](pull-requests.md)中列出的 review 与 checks；
1. 确认 README、当前文档与 examples 只描述最终公共契约，documentation contract、两套类型检查和 strict docs build 全部通过；
1. 在 PR preview 人工检查架构图、配置表、代码块换行与 prerelease 提示；
1. 本地或 CI 验证 wheel、sdist 及包元数据：

```bash
make build-artifacts
```

该 target 内部执行 `uv build --no-sources`、pinned `twine==6.2.0 check` 和仓库外隔离安装 smoke。`--no-sources` 很重要：发布构建不得因本地 workspace source 覆盖而得到一个无法从锁定依赖重现的产物。

涉及 package resources 或 native extra 的版本还必须在仓库外、清空 `PYTHONPATH`后安装真实产物。0.8 的门禁要求 Python 3.10–3.14 验证 wheel，Python 3.12 至少验证一次 sdist；检查全部 package resources 非空且登记在 `RECORD`，验证 bare core不安装任何 backend，执行 NoneBot load、Preparation 与 typed artifact smoke，并在`[htmlkit]`、`[takumi]` 和 `[pillow,skia]` 的独立环境中确认锁定依赖和真实 native
PNG 渲染。

## 并行开发与 release cut

多条 `feat/*`、`fix/*` 可以同时工作，但版本号只在显式的 release PR 中变化：

1. 功能和修复分支从 `master` 创建，各自完成实现、测试与文档；普通功能 PR 不提前修改项目版本；
1. 准备发版时，只把已经可发布的变更合入 `master`，未完成分支继续保持开放或放在 feature flag 后；
1. 从选定的 `master` 快照创建短生命周期 `release/v<version>`，集中完成 `uv version <version>`、锁文件、迁移说明和 release notes；
1. release PR 使用与普通 PR 相同的 review、preview 和 required checks，最终 squash merge；不要在 PR 合并前手工创建 tag；
1. 合并后的四条 master workflow 按精确 source SHA 保留运行。后续 PR 即使很快合并，也不会取消或混入本次版本门禁；
1. Auto Tag 只给版本变化的 trusted master SHA 打 tag，因此版本边界由该提交确定，而不是由发布 workflow 启动时仍在移动的 `master` 决定。

当前自动发布只授权 `master` 历史。若未来需要同时维护 `0.8` 与 `0.9` 两条已分叉的稳定线，应先设计受保护的 maintenance branch、回合并规则和 tag 授权，再扩展 ancestry gate；不要临时从维护分支打 tag 后绕过校验。

## 自动发布主链路

```mermaid
flowchart LR
    A["版本 PR squash merge"] --> B["同一 master SHA 的<br/>CI + Coverage + Docs + Prek"]
    B --> R["workflow_run 汇合门禁<br/>四条全部 completed/success"]
    R --> P["比较 first parent/current version<br/>PEP 440 + package preflight"]
    P --> C["创建 v&lt;version&gt; tag<br/>指向 trusted master SHA"]
    C --> D["Publish: resolve + verify"]
    D --> E["Build + twine check"]
    E --> F["PyPI trusted publishing"]
    F --> V["回读 PyPI<br/>核对 filename + SHA-256"]
    V --> G["GitHub Release + artifacts"]
    G --> I["从同一 tag 部署<br/>versioned docs on gh-pages"]
```

### Auto Tag on Version Change

`Auto Tag on Version Change` 监听 `CI`、`Coverage`、`Docs`、`Prek` 的 `workflow_run: completed` 事件。每个完成事件都只在受信任的 `master` push 上参与汇合，因此版本 PR 可以来自 fork，不需要让 fork PR workflow 持有写权限。

1. 以 `workflow_run.head_sha` 为唯一 source SHA，通过 Actions API 查询同一 SHA、`master`、`push` 事件的四条 required workflow；任一缺失、未完成、失败或取消时正常结束且不创建 tag；required workflows 不会用后续 master push 取消旧 source SHA；
1. 四条全部成功后检出该精确 SHA，并确认它位于 `origin/master`；同一 SHA 的多个完成事件按 concurrency key 串行化；
1. 从 source SHA 第一父提交的 `pyproject.toml` 读取旧版本，再与当前项目版本比较；版本相同则正常结束；
1. 只有版本实际变化时才用 pinned `packaging` 验证 PEP 440：新旧版本必须使用 canonical spelling，新版本必须严格递增，且不能带 PyPI 不接受的 local segment；
1. 在 tag 产生前检查锁文件，构建唯一 wheel/sdist 并执行 pinned Twine 校验；package preflight 失败不会占用版本号；
1. preflight 成功后解析 `v<version>` 并查询远程 tag；tag 不存在时创建带注解 tag，使其准确指向本次 trusted master SHA；已指向同一 SHA 时复用，指向其他 commit 时失败；
1. 以该 tag ref 显式 dispatch `Publish`；dispatch 前按 source SHA 查询既有 run，避免多个完成事件重复发布。

普通 PR、只修改依赖配置的 PR 或未改变 `project.version` 的 master commit 都不会创建 tag。版本更新必须位于最终 squash/merge commit，确保第一父提交与 gated source 的版本差异可审计。

如果 Auto Tag 的构建 preflight 因 workflow 基础设施缺陷失败且尚未创建 tag，先通过 PR 修复基础设施，并等待修复后当前 `master` SHA 的 CI、Coverage、Docs、Prek 全部成功。随后从默认分支手动运行 `Auto Tag on Version Change`，输入该完整 `source_sha`。恢复入口只接受当前 `master` tip、重新汇合该精确 SHA 的四条门禁、要求目标 tag 尚不存在，并再次执行完整 package preflight；它不能用于已有 tag 的发布恢复，也不能选择历史 commit。已有 tag 应直接按下文重跑 `Publish`。

由 `GITHUB_TOKEN` push 产生的事件不会再次触发普通 downstream workflow；显式 `workflow_dispatch` 是发布契约的一部分，也使同一 tag 的恢复可重复执行。

### Publish 的不可逆操作前校验

任何 PyPI 上传发生前，`Publish` 都必须解析并验证唯一发布 tag：

- tag 名符合 `v<version>`；
- tag 确实存在，checkout 的 `HEAD` 与 tag 指向同一 commit；
- 该 commit 位于 `origin/master` 历史中；
- tag 去掉前缀 `v` 后与 `pyproject.toml` 的项目版本完全一致；
- `uv build --no-sources` 与 `twine check` 成功。

验证和构建 job 只需要只读权限。构建产物通过 artifact 传给后续 job；只有 PyPI job 获得 OIDC `id-token: write`，只有 GitHub Release job 获得写 release 所需的 `contents: write`。

### PyPI 与 GitHub Release

PyPI 使用 `release` environment 和 trusted publishing，不保存长期 API token。上传完成后，独立 verification job 会重试读取 PyPI JSON，并要求远端文件集合与本次 artifact 的 filename、SHA-256 **完全一致**。只有这个不可变远端状态通过验证，GitHub Release 才会绑定同一个 tag 并附加同一批 wheel 与 sdist。这样恢复时即使使用 `skip-existing`，也不会让 PyPI 与 GitHub Release 指向不同字节。

`Publish` 不监听 tag push；Auto Tag 在精确 SHA 门禁成功后显式 dispatch。手动运行只用于恢复或维护者明确批准的发布，必须提供已经存在的 `release_tag`。workflow definition 只能从默认分支或与输入一致的 tag ref 运行，并仍执行全部 source/version/build/hash 校验，不能用 feature branch workflow、手工误建 tag 或手动输入绕过发布不变量。`v*` tag 的不可变 Ruleset 和 `release` environment policy 见[仓库治理与保护](governance.md)。

## TestPyPI

`Publish (TestPyPI)` **只支持维护者手动触发**，不会在每个 PR 上自动上传。它从当前项目版本生成唯一 dev version，构建并校验产物，再通过 `testpypi` environment 的 trusted publishing 上传。

TestPyPI 用于安装行为或包元数据的人工验收，不是 PR 必需 check，也不能替代正式发布前的 tag/source/version 校验。

## 文档是独立发布链路

`Docs` 覆盖每个 `master` push，使正常 release cut 和 pre-tag recovery 选择的任意当前 `master` SHA 都具备可汇合的精确 SHA 门禁。它执行严格构建，但不写正式 Pages 版本。

`Publish versioned documentation` 位于不可逆软件发布之后：它重新检出经过验证的 tag、再次 strict build，并在 PyPI hash 回读与 GitHub Release 均成功后才通过 `mike` 创建 `/<version>/` 和更新 `latest`。

因此：

- 版本 PR 的 tag 必须等待同一 SHA 的 Docs workflow 成功；
- Docs 成功不代表 PyPI / GitHub Release 成功，也不会让未发布版本提前成为 `latest`；
- PyPI / GitHub Release 成功后，版本文档仍可能因 Pages 瞬时故障失败；对同一 tag 重跑 `Publish` 即可恢复；
- PR 文档预览目录不属于正式版本，关闭 PR 后会由独立 cleanup workflow 删除。

版本目录和 `gh-pages` 写入策略见 [文档版本管理](documentation-versioning.md)。

## 部分失败恢复 { #partial-failure-recovery }

先确认已完成到哪一条不可逆边界，再只恢复失败链路：

| 状态                                         | 恢复方式                                                                                                                                      |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Auto Tag package preflight 失败，尚未创建 tag | 基础设施缺陷先通过 PR 修复；四条 required workflow 在修复后的当前 `master` SHA 全部成功后，以该完整 SHA 手动运行 `Auto Tag on Version Change`；产物或 metadata 缺陷则提升版本并走新的版本 PR |
| tag/source/version 不变量校验失败            | 停止发布并核对 tag 来源；代码或版本确有错误时发起新的版本 PR。除非维护者确认 tag 从未对外发布且明确承担历史变更风险，否则不要移动或重建原 tag |
| build / `twine check` 失败，尚未上传 PyPI    | 基础设施瞬时故障可对同一 tag 重跑；产物或 metadata 确有错误时提升版本并走新的版本 PR                                                          |
| 校验和构建成功，PyPI 因临时故障失败          | 对同一已验证 tag 重新运行 `Publish`                                                                                                           |
| PyPI 已成功，GitHub Release 失败             | 优先重跑保留原 artifact 的 workflow；重跑发布恢复路径时，PyPI hash verification 必须证明重建产物与已发布文件相同，才会补齐 GitHub Release     |
| PyPI 已有同名文件但 hash verification 不一致 | 立即停止自动恢复；保留双方 hash 和 workflow artifact，核对最初发布 run，不得用 `--clobber` 把不同字节附到 GitHub Release                      |
| GitHub Release 已存在但附件缺失              | 核对 tag 和 PyPI 文件哈希后，重新运行或从该 workflow 的已验证 artifact 补齐附件                                                               |
| Docs 门禁失败，尚未创建 tag                  | 瞬时故障只重跑同一 source SHA；真实缺陷必须通过新 PR 修复并重新执行 release cut，汇合门禁成功前不得手工补 tag                                 |
| PyPI / GitHub Release 成功，版本文档失败      | 保留已经发布的软件版本，对同一 tag 重跑 `Publish` 以补齐 Pages；不得移动 tag、重发版本或从 release 分支复制 `site/`                           |

!!! danger "不要覆盖已发布版本"

    PyPI 文件不可替换。只要任一产物已经发布，就不得复用版本号重新构建，也不得移动对应 tag。需要修改代码或产物时必须提升版本并走新的版本 PR。

## 发布后核对

- PyPI 页面显示目标版本，wheel 与 sdist 均存在；
- 从 PyPI 安装的包能被 NoneBot 加载；
- GitHub Release 指向正确 tag，附件与 PyPI 产物一致；
- 版本 URL 与 `latest` 可访问，页面内容来自同一个 release tag；
- `master`、tag、包元数据与文档展示的版本一致；
- 对任何失败保留 workflow run、artifact 和恢复操作记录。
