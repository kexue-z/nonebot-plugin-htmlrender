## 背景

<!-- 需要解决什么问题？关联 issue 时使用 `Closes #123`。 -->

## 方案

<!-- 描述实现边界、重要取舍，以及为什么选择该方案。 -->

## 行为、兼容性与风险

<!-- 用户可见变化、breaking change、配置迁移、性能或安全影响。无则写“无”。 -->

## 验证

<!-- 列出实际运行的命令和结果，不要只写“测试通过”。 -->

- [ ] `make ruff-format-check`
- [ ] `make ruff-check`
- [ ] `make typecheck`
- [ ] `make ty`
- [ ] `make test-ci`
- [ ] `prek run --all-files`
- [ ] workflow 变更已运行 `prek run actionlint --all-files --hook-stage=manual`，或本项不适用
- [ ] 已按改动范围运行 package / docs / local browser / remote smoke 检查，或说明不适用原因
- [ ] 已新增或更新回归测试

## 文档

- [ ] 已更新受到影响的用户与维护者文档，或本次不需要文档变更
- [ ] 文档相关变更通过 strict build，并检查 CI 评论中的预览页面

## 合并前

- [ ] PR 标题可作为符合 `type(scope): subject` 的 squash commit subject
- [ ] 已处理阻塞 review，并在实质性更新后重新请求 review
- [ ] 分支已更新到最新 `master`，所有适用 checks 通过
