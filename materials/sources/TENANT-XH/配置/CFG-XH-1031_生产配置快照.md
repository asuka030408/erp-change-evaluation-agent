# ERP 采购申请生产配置快照

- 文档 ID：CFG-XH-1031
- 租户：TENANT-XH
- 采集时间：2026-10-31 18:00（Asia/Shanghai）
- 状态：只读导出；由系统管理员核对；不是业务授权文件
- 环境：生产；规则包 `PR-APPROVAL-v3.4`

## CFG-XH-1031 §1 普通采购

`request_type=NORMAL`、`currency=CNY` 时，系统以 `tax_included_amount` 判断：金额 `<=100000.00` 走 `DEPT_MANAGER -> PROCUREMENT_MANAGER`；金额 `>100000.00` 走 `DEPT_MANAGER -> PROCUREMENT_MANAGER -> FINANCE_OWNER`。总部与全部子公司共用此规则。

## CFG-XH-1031 §2 紧急采购

仅 `org=HQ` 且 `request_type=EMERGENCY` 时，部门经理审批后可生成订单，并创建 24 小时补审任务，要求采购经理与财务负责人完成补审。其他组织的 `EMERGENCY` 申请被退回人工处理。

## CFG-XH-1031 §3 通用约束

`requester_id` 与任何审批节点的 `approver_id` 相同时，禁止自审并转入代理审批队列。审批路径变更只对新提交的申请生效；在途申请按原路径运行，除非经业务负责人批准迁移方案。

## CFG-XH-1031 §4 快照局限

本文件反映采集时的系统配置；不能证明配置符合合同，也不能证明未来变更已被批准。若与正式决定不一致，应报告差异并人工核验。
