# 采购申请与订单、财务系统接口说明

- 文档 ID：IF-XH-PR-01
- 租户：TENANT-XH
- 版本：2.3
- 更新日期：2026-08-05
- 状态：已发布接口说明；与生产接口版本一致

## IF-XH-PR-01 §1 订单接口

ERP 在采购申请完成其适用审批路径后，向订单系统发送 `PR_APPROVED` 事件，字段含 `request_id`、`org_id`、`request_type`、`tax_included_amount`、`approval_status`、`approved_at`。总部紧急采购按 CO-XH-017 可在部门经理审批后发送 `PR_EMERGENCY_RELEASED`，并在补审完成后发送 `PR_EMERGENCY_COMPLETED`。

## IF-XH-PR-01 §2 财务同步

财务系统接收 `PR_APPROVED`、`PR_EMERGENCY_COMPLETED` 事件及金额、组织、审批人列表。财务系统目前不接收“阈值版本号”，因此若修改阈值，需评估审计追溯是否需要增加字段或另建映射表。

## IF-XH-PR-01 §3 变更影响

仅改变普通采购审批阈值时，现有事件字段可继续使用，但须回归验证 50,000、100,000 元边界及订单生成时机；如需传送新的审批节点、试点标识或阈值版本，应另行评估接口变更、消费者兼容性及费用。

## IF-XH-PR-01 §4 异常

事件失败进入重试队列；重复事件以 `request_id + event_type` 幂等处理。改变审批路径后须测试补发事件不会生成重复订单。
