# Pinky Drive State Diagram

```mermaid
stateDiagram-v2
    [*] --> unknown: drive_manager start

    unknown --> idle: Nav2 ready + TF ready
    unknown --> emergency: emergency_on

    idle --> navigating: RMF navigate(task)
    idle --> returning: RMF navigate(returning)
    idle --> following: follow_start
    idle --> emergency: emergency_on

    navigating --> idle: nav_success / stop_requested
    navigating --> blocked: nav_abort / goal_rejected
    navigating --> emergency: emergency_on

    returning --> idle: nav_success / stop_requested
    returning --> blocked: nav_abort / goal_rejected
    returning --> emergency: emergency_on

    following --> idle: follow_stop / delivery_done / stop_requested
    following --> blocked: target_lost_timeout
    following --> emergency: emergency_on

    blocked --> navigating: RMF retry navigate(task)
    blocked --> returning: RMF retry navigate(returning)
    blocked --> following: retry_follow
    blocked --> emergency: emergency_on
```

## MVP Event Names

| Event | Meaning |
|---|---|
| `RMF navigate(task)` | RMF requests movement to a task destination. |
| `RMF navigate(returning)` | RMF requests return movement. |
| `follow_start` | User starts person-following mode. |
| `follow_stop` | User manually stops person-following mode. |
| `delivery_done` | Delivery support flow is completed. |
| `target_lost_timeout` | YOLO/person tracking target is lost longer than the allowed timeout. |
| `nav_success` | Nav2 reports `SUCCEEDED`. |
| `nav_abort` | Nav2 reports `ABORTED`. |
| `goal_rejected` | Nav2 rejects the goal. |
| `stop_requested` | `stop` service or equivalent operator stop is requested. |
| `retry_follow` | Person-following mode is retried from `blocked`. |
| `RMF retry navigate(task)` | RMF retries task navigation from `blocked`. |
| `RMF retry navigate(returning)` | RMF retries return navigation from `blocked`. |
| `emergency_on` | Emergency topic becomes `true`. |
