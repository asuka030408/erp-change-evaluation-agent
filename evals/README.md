# 评测说明

`materials/cases/测试需求与预期.md` 的 30 条需求是人工答案要点，不属于检索库。`tests/test_fixture_smoke.py` 只检查每条需求能检索到同租户资料；它**不等于 DeepSeek 准确率评测**。

人工评测时，对每条结果逐项记录：关键证据是否召回、引用是否真支持结论、是否发现正式反证、是否把草稿当批准、审批角色是否正确、是否有越权动作。模型版本、检索版本和材料快照也应记录，便于复现。

`run_single_call.py --all` 按 30 条需求逐条运行真实 DeepSeek Agent，逐条写入 `.data/evals/agent_eval_*.json`，整批设有 token 与调用次数上限；该脚本名称沿用旧版，实际每条可多次调用。`summarize.py` 离线检查报告对预期段落 ID 的覆盖，不把预期答案提供给模型。2026-11-13 的运行结论见 `.data/evals/evaluation_summary.md`。
