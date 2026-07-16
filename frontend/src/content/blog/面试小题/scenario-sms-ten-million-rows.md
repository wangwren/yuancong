---
title: 医院挂号系统：千万级数据的定时短信通知
description: 每天定时给千万级数据量的用户表发短信通知，查询和分批处理怎么设计。
pubDate: 2026-04-21
tags: [场景题]
---
医院挂号系统，每天晚上六点需要给明天需要来医院的用户发送短信通知。数据库表中数据量有 一千万条。(其他场景也都类似，就是大数据量查询数据库)

#### 数据库表设计
```sql
CREATE TABLE appointment (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    patient_name VARCHAR(50),
    phone VARCHAR(20),
    appointment_date DATE,       -- 预约日期
    department VARCHAR(50),      -- 科室
    doctor_name VARCHAR(50),
    status TINYINT DEFAULT 0,    -- 0待就诊 1已就诊 2已取消
    sms_sent TINYINT DEFAULT 0,  -- 0未发送 1已发送 2发送失败
    created_at DATETIME
);
```
#### 索引优化
```sql
ALTER TABLE appointment
ADD INDEX idx_date_status_sms (appointment_date, status, sms_sent);
```
遵循 最左前缀原则：

appointment_date — 等值查询，区分度最高，放最前面
status — 等值条件，继续缩小范围
sms_sent — 等值条件，进一步过滤

三个条件组合后，索引能精准定位到目标数据，千万级表也能毫秒级返回。

#### 游标分页(重点)
为什么需要分页？
假设明天有几万条预约，一次性加载到内存不合适，需要分批查询。
传统分页的问题
```sql
-- 传统分页：第100页
SELECT ... LIMIT 49500, 500;
```
数据库要先扫描前 49500 条然后丢弃，只返回后 500 条，越往后越慢。

**游标分页的写法**

```sql
-- 第一批：id > 0 表示从头开始
SELECT id, patient_name, phone, department, doctor_name
FROM appointment
WHERE appointment_date = '2026-04-11'
  AND status = 0
  AND sms_sent = 0
  AND id > 0 -- 主要
ORDER BY id ASC
LIMIT 500;

-- 后续批次：用上一批最后一条的 id
SELECT id, patient_name, phone, department, doctor_name
FROM appointment
WHERE appointment_date = '2026-04-11'
  AND status = 0
  AND sms_sent = 0
  AND id > 3720    -- 上一批最后一条的 id
ORDER BY id ASC
LIMIT 500;
```
游标分页的执行过程

联合索引定位：通过 `idx_date_status_sms `定位到所有满足业务条件的记录（千万 → 几千条）
id 过滤：在这个结果范围内，跳过 `id <= lastId` 的记录(要的是 id>lastId 的数)
顺序读取：按 `id ASC` 排序，读够 500 条就停，不会扫描全部数据

核心理解：联合索引负责筛选，id 负责翻页定位。数据库不会把所有符合条件的数据都查出来，而是"定位 → 顺序读 → 够数就停"。

#### 常见错误写法
##### 用 id 范围代替游标分页
```sql
-- 错误写法：每次 id 加 500
SELECT ...
WHERE ...
  AND id > 3720
  AND id < 4220;   -- 3720 + 500
```
为什么有问题？
id 不一定是连续的。 中间有大量被删除的、被取消的、或者不满足条件的记录，id 之间有空洞。
例如满足条件的 id 分布：`3721, 3725, 3890, 4100, 4501, 4802, 5310, ...`
用 `id > 3720 AND id < 4220 `可能只命中 4 条，远不到 500 条。更极端的情况下，某个区间一条都没有，程序却以为处理完了。
正确做法：用` id > lastId ORDER BY id ASC LIMIT 500`，让数据库自己去找接下来的 500 条。

#### Java代码实现
```java
@Scheduled(cron = "0 0 18 * * ?")
public void sendAppointmentReminder() {
    Long lastId = 0L;
    int batchSize = 500;

    while (true) {
        // 每次从上一批最后一个 id 之后开始取
        List<Appointment> batch = appointmentMapper.selectBatch(
            LocalDate.now().plusDays(1), lastId, batchSize
        );

        // 取不到数据说明全部处理完了
        if (batch.isEmpty()) {
            break;
        }

        for (Appointment apt : batch) {
            try {
                smsService.send(apt.getPhone(), buildContent(apt));
                appointmentMapper.updateSmsSent(apt.getId(), 1);
            } catch (Exception e) {
                appointmentMapper.updateSmsSent(apt.getId(), 2);
                log.error("短信发送失败, id={}", apt.getId(), e);
            }
        }

        // 更新游标为这一批最后一条的 id
        lastId = batch.get(batch.size() - 1).getId();
    }
}
```
#### mapper层
```java
@Select("SELECT id, patient_name, phone, department, doctor_name " +
        "FROM appointment " +
        "WHERE appointment_date = #{date} " +
        "AND status = 0 AND sms_sent = 0 " +
        "AND id > #{lastId} " +
        "ORDER BY id ASC LIMIT #{batchSize}")
List<Appointment> selectBatch(
    @Param("date") LocalDate date,
    @Param("lastId") Long lastId,
    @Param("batchSize") int batchSize
);
```
