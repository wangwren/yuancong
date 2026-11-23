---
title: Java 高级开发面试题：Dubbo、ZooKeeper、WebSocket 与常用中间件
description: Dubbo 调用过程和容错、ZooKeeper、WebSocket 握手与多机推送、ES、MongoDB、Memcached、Oracle、分布式事务，以及行情推送、直播弹幕、礼物打赏三道场景题。
pubDate: 2026-11-23
tags: [Java, 场景题]
---

## 一、Java 基础、JVM、并发

高频题，先能用一句话答上来：

| 题 | 一句话 |
|---|---|
| HashMap 和 ConcurrentHashMap | JDK 8 的 ConcurrentHashMap：桶是空的用 CAS 放，不空就锁住桶的第一个节点；读不加锁 |
| synchronized 锁升级 | 无锁 → 偏向锁 → 轻量级锁（CAS 自旋）→ 重量级锁（挂起线程）；偏向锁 JDK 15 起默认关闭 |
| AQS、ReentrantLock | 一个 state 计数 + 一个等待队列；抢不到就入队挂起，释放时唤醒下一个 |
| volatile | 保证可见性、禁止指令重排序，不保证原子性（`i++` 不行） |
| 线程池参数和执行流程 | 先用核心线程 → 核心满了进队列 → 队列满了开到最大线程 → 再满走拒绝策略 |
| JVM 内存结构 | 堆、元空间、虚拟机栈、本地方法栈、程序计数器；堆外还有直接内存 |
| CMS 和 G1 | G1 把堆分成很多小块（Region），优先回收垃圾最多的块，所以能控制停顿时间 |
| Full GC 排查 | jstat 看回收效果 → jmap 导堆 → MAT 看谁占内存 → 定位代码 |
| 类加载、双亲委派 | 先交给父加载器，父加载器加载不了才自己加载；防止核心类被替换 |
| 直接内存、零拷贝 | 堆外内存，IO 时少复制一次；靠 GC 回收堆里对应的小对象来释放（详见[《Java 直接内存》](/blog/java-direct-memory/)） |
| 虚拟线程 | JDK 21，阻塞时从平台线程上卸下来，适合大量等 IO 的任务 |

### CompletableFuture 不指定线程池，用的是哪个？会有什么问题？

**结论**：不传线程池时，`supplyAsync` / `runAsync` 用的是 `ForkJoinPool.commonPool()`，整个 JVM 共用一个。

- JDK 8 里公共池的线程数默认是「CPU 核数 − 1」；如果算出来 ≤ 1（比如容器只给了 1–2 核），CompletableFuture 会改成**每个任务新建一个线程**。
- 问题：公共池是全 JVM 共享的，并行流也在用。如果任务里调外部接口这类阻塞操作，几个慢请求就能把这几个线程全占住，别的地方也跟着变慢。
- 正确做法：IO 类任务传自己的线程池（有界队列、线程起名字、明确的拒绝策略）；`allOf(...).get()` 加超时；单个任务用 `exceptionally` / `handle` 出错时给默认值，不让一个慢任务拖垮整个请求。

### ThreadLocal 的原理？为什么会内存泄漏？

每个线程对象（Thread）里有一个 ThreadLocalMap，key 是 ThreadLocal 对象（弱引用），value 是你存的值。`get` / `set` 时拿当前线程自己的 map 去查，所以线程之间互不影响。

**泄漏**：线程池里的线程一直活着，map 也一直在；ThreadLocal 对象没人引用后，弱引用的 key 被回收变成 null，但 value 还被 map 强引用着，不调 `remove` 就一直占内存。

**更常见的坑**：线程复用，上一个请求放进去的用户信息没清，下一个请求读到了别人的数据。所以用完在 `finally` 里 `remove()`。

**追问**：父子线程传值？→ `InheritableThreadLocal`（只在创建子线程时复制一次）；线程池里传值用阿里开源的 TransmittableThreadLocal。

### 死锁怎么排查？怎么避免？

排查：`jstack PID`，输出末尾会有 `Found one Java-level deadlock`，列出每个线程持有哪把锁、在等哪把锁；Arthas 用 `thread -b`。

避免：所有地方按固定顺序加锁；用 `tryLock` 带超时，拿不到就放弃；缩小加锁范围。

### 线上 CPU 100%，怎么查？

1. `top` 找到 CPU 高的 Java 进程号（PID）；
2. `top -Hp PID` 看这个进程里哪个线程 CPU 高，记下线程号；
3. `printf '%x\n' 线程号` 转成十六进制（jstack 里线程号是十六进制的 nid）；
4. `jstack PID | grep -A 20 0x十六进制号` 看这个线程正在执行哪行代码。

常见原因：死循环、正则表达式回溯、大量计算、频繁 GC（如果高的是 GC 线程）。用 Arthas 更快：`thread -n 3` 直接列出最忙的 3 个线程和调用栈。

**追问**：占 CPU 的是 GC 线程？→ 转去查内存：`jstat -gcutil PID 1000` 看每次回收效果，再 jmap 导出堆、用 MAT 分析，排查过程见[《短信平台频繁 Full GC 问题排查与优化》](/blog/scenario-full-gc-tuning/)。

### 接口突然变慢，怎么查？

先分范围：是所有接口都慢（看机器负载、GC、数据库），还是某一个接口慢。单个接口用 Arthas `trace 类名 方法名` 看每一步花了多少时间。常见原因：慢 SQL（慢查询日志 + EXPLAIN）、调外部接口超时、线程池排队、锁竞争、Full GC 停顿。

## 二、Spring、MyBatis、Spring Boot

### Spring MVC 处理一个请求的流程

1. 请求进入 `DispatcherServlet`（总入口）；
2. `HandlerMapping` 按 URL 找到对应的 Controller 方法；
3. 执行拦截器的 `preHandle`；
4. `HandlerAdapter` 负责调用：先用参数解析器把请求参数、JSON 请求体（靠 `HttpMessageConverter`）转成方法参数，再调 Controller；
5. 返回值：有 `@ResponseBody` 就用 `HttpMessageConverter` 写成 JSON；否则返回视图名，由 `ViewResolver` 找到页面渲染；
6. 拦截器 `postHandle`、`afterCompletion`；中间抛异常由 `@ControllerAdvice` 统一处理。

**追问**：过滤器和拦截器的区别？→ 过滤器（Filter）是 Servlet 规范的，在 DispatcherServlet 之前执行，拿不到要调哪个方法；拦截器是 Spring 的，在 DispatcherServlet 里面执行，能拿到目标方法。

### MyBatis 里 `#{}` 和 `${}` 的区别

`#{}` 是预编译占位符，SQL 里变成 `?`，参数单独传给数据库，能防 SQL 注入。`${}` 是把字符串直接拼进 SQL，只在表名、排序字段这种不能用 `?` 的地方用，而且要自己做白名单校验。

### Mapper 只有接口没有实现类，为什么能调用？

MyBatis 为每个 Mapper 接口生成一个 JDK 动态代理对象（`MapperProxy`）。调方法时，代理按「接口全名 + 方法名」找到 XML 或注解里对应的 SQL（`MappedStatement`），交给 `SqlSession` 执行，再把结果映射成 Java 对象。和 Spring 整合后，`@MapperScan` 把这些代理对象注册成 Bean，所以能直接注入。

### MyBatis 一级缓存、二级缓存

**一级缓存**在 SqlSession 里，默认开启：同一个 SqlSession 里同样的查询第二次不查库；执行增删改或提交会清空。和 Spring 整合后，不在事务里时每次调用都用新的 SqlSession，一级缓存基本不起作用；在同一个事务里才生效。

**二级缓存**按 Mapper（namespace）共享，要手动开（XML 里加 `<cache/>`）。多表关联时一个 Mapper 改了数据，另一个 Mapper 的缓存不知道，容易读到旧数据，所以生产一般不开，用 Redis 代替。

### Spring Boot 自动配置的原理

`@SpringBootApplication` 里包含 `@EnableAutoConfiguration`，它通过 `AutoConfigurationImportSelector` 读出所有 jar 里登记的自动配置类清单（老版本登记在 `META-INF/spring.factories`，新版本在 `META-INF/spring/` 目录下、以 `AutoConfiguration.imports` 结尾的那个文件），再用条件注解筛选：

- `@ConditionalOnClass`：类路径里有这个类才生效（引了 starter 才配置）；
- `@ConditionalOnMissingBean`：你自己没定义这个 Bean 才生效（所以自己定义就能覆盖默认的）；
- `@ConditionalOnProperty`：配置项满足才生效。

**追问**：自己写一个 starter？→ 写自动配置类（加条件注解）+ 配置属性类（`@ConfigurationProperties`）+ 把自动配置类登记到上面的清单文件。

### AOP 怎么实现的？JDK 动态代理和 CGLIB 有什么区别？

Spring 在 Bean 初始化之后（`BeanPostProcessor` 阶段）给需要增强的 Bean 生成代理对象，放进容器的是代理。调方法时先走代理里的增强逻辑（事务、日志），再调原对象。

JDK 动态代理要求有接口，代理类实现同样的接口；CGLIB 生成目标类的子类，所以 `final` 类和 `final` 方法增强不了。

同一个类里一个方法调另一个方法不经过代理，所以 `@Transactional` 会失效。

## 三、MySQL 和 SQL 优化

### 慢 SQL 怎么优化？说说步骤

1. **找**：慢查询日志（`slow_query_log`、`long_query_time`）或监控里的慢 SQL。
2. **看**：`EXPLAIN` 重点看四列——`type`（ALL 是全表扫描，range / ref / const 依次更好）、`key`（实际用了哪个索引）、`rows`（预计扫多少行）、`Extra`（Using filesort 要额外排序、Using temporary 用了临时表、Using index 是覆盖索引不用回表）。
3. **改**：建或调整联合索引（注意最左前缀）；不在索引列上套函数、不让类型隐式转换；只查需要的列争取覆盖索引；深分页改写；大的 IN 拆批；复杂 JOIN 拆开。
4. **验**：改完再 EXPLAIN，并对比执行时间。

### `LIMIT 1000000, 20` 为什么慢？怎么优化？

MySQL 要先读出前 1000020 行再扔掉前 100 万行，而且每行都要回表，非常浪费。

① 记住上一页最后一条的 id，下一页从它后面取（最快，但不能直接跳到第 N 页）；② 延迟关联：先只在索引上查出这 20 个 id，再用 id 回表取整行。

```sql
-- ① 按上一页最后的 id 往后取
SELECT * FROM orders WHERE id > 上一页最后的id ORDER BY id LIMIT 20;
-- ② 延迟关联：子查询只走索引
SELECT o.* FROM orders o
JOIN (SELECT id FROM orders ORDER BY id LIMIT 1000000, 20) t ON o.id = t.id;
```

### 大表加字段、加索引会锁表吗？

MySQL 支持在线改表（Online DDL），大部分加索引、加列操作执行期间允许读写，只在开始和结束时短暂拿元数据锁。风险：如果有长事务没结束，改表语句会一直等元数据锁，后面的读写也全部排在它后面被堵住。大表常用 gh-ost 或 pt-online-schema-change：建新表 → 拷数据 → 同步增量 → 最后切换。选在低峰执行。

### 什么时候分库分表？分完有什么问题？

单表数据量和写入压力大到索引、备份、改表都吃力时才做（「单表千万级」是经验说法，不是硬标准）。按用户 ID 或订单号取模、或按时间范围分。分完的问题：跨库 JOIN、跨库事务、全局唯一 ID（雪花算法）、按非分片字段查询（建映射表或同步到 ES）、扩容时的数据迁移。常用 ShardingSphere。

## 四、RabbitMQ

### RabbitMQ 有哪几种交换机？

消息先发到交换机（exchange），交换机按规则转给队列：

- **direct**：路由键完全相等才转；
- **topic**：路由键按通配符匹配，比如 `quote.sh.*`；
- **fanout**：发给绑定的所有队列，就是广播；
- **headers**：按消息头匹配，很少用。

行情、直播弹幕广播给多台推送机器，就是 fanout 的典型用法（见下面 WebSocket 一节的多机推送图）。

### 消息重复消费怎么办？

MQ 只能保证「至少送到一次」，重复是正常现象（比如处理完还没来得及确认就断了，消息会重投）。所以消费端要做幂等：

1. 业务唯一号 + 唯一索引，插入冲突就说明处理过了；
2. 状态机带条件更新：`UPDATE … WHERE status = '待处理'`，影响 0 行就跳过；
3. Redis `SET 消息ID NX EX 过期时间` 记录处理过的消息。

### 消息积压了怎么办？

先恢复：加消费者实例、调大单个消费者的并发和预取数量（prefetch）。再查原因：消费慢是不是卡在数据库或外部接口。积压特别多时，临时把消息转存到新队列或表里，后面慢慢处理。预防：监控队列长度，超过阈值告警。

### 延迟消息怎么做？（比如订单 30 分钟没支付自动取消）

1. 消息过期时间（TTL）+ 死信交换机：消息过期后被转到死信队列，消费死信队列执行取消。一个队列里最好只放同一种过期时间；
2. 装延迟消息插件（`rabbitmq_delayed_message_exchange`）；
3. 不用 MQ：Redis 有序集合（ZSet）用到期时间当分数，定时任务取出到期的处理。

## 五、Dubbo 和 ZooKeeper

### 先看要解决什么问题

服务 A 要调服务 B 的接口。B 有好几台机器，会扩容、重启、宕机，IP 会变。要解决三件事：

1. B 现在有哪几台、地址是什么？→ **注册中心**（一本随时更新的通讯录），这是 ZooKeeper 的活；
2. 这么多台挑哪台调？→ **负载均衡**；
3. 怎么像调本地方法一样调另一台机器上的方法？→ **动态代理 + 网络传输 + 序列化**（把对象变成字节发过去）。

2 和 3 是 Dubbo 管的。

<figure class="fig">
<div class="fig-box">
<svg viewBox="0 0 720 290" role="img" aria-label="Dubbo 与 ZooKeeper：注册、订阅、通知、直接调用">
<defs><marker id="iq1-a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah" d="M0 0L10 5L0 10z"/></marker><marker id="iq1-p" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah-pri" d="M0 0L10 5L0 10z"/></marker><marker id="iq1-s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah-sec" d="M0 0L10 5L0 10z"/></marker></defs>
<rect class="bx-heap" x="255.8" y="16" width="208.4" height="64" rx="8"/>
<text class="t-b" x="360" y="43" text-anchor="middle">注册中心 ZooKeeper</text>
<text class="t-s" x="360" y="64" text-anchor="middle">/dubbo/接口全名/providers</text>
<rect class="bx" x="28.4" y="196" width="217.9" height="74" rx="8"/>
<text class="t-b" x="137.4" y="225" text-anchor="middle">消费者</text>
<text class="t-s" x="137.4" y="248" text-anchor="middle">内存里存一份提供者地址列表</text>
<rect class="bx" x="473.7" y="196" width="217.9" height="74" rx="8"/>
<text class="t-b" x="582.6" y="225" text-anchor="middle">提供者（多台）</text>
<text class="t-s" x="582.6" y="248" text-anchor="middle">业务线程池处理请求</text>
<path class="ln" d="M568.4 194L437.7 84" marker-end="url(#iq1-a)"/>
<text x="530.5" y="128">① 启动时写入自己的地址</text>
<text class="t-s" x="530.5" y="147">临时节点：宕机后自动消失</text>
<path class="ln" d="M189.5 194L301.3 84" marker-end="url(#iq1-a)"/>
<path class="ln ln-sec ln-dash" d="M276.6 84L162.9 194" marker-end="url(#iq1-s)"/>
<text x="15.2" y="118">② 启动时订阅提供者列表</text>
<text class="t-sec" x="15.2" y="138">③ 列表变了，推送新列表</text>
<path class="ln ln-pri" d="M248.2 233L471.8 233" marker-end="url(#iq1-p)"/>
<text class="t-pri" x="360" y="222" text-anchor="middle">④ 直接调用，不经过注册中心</text>
<text class="t-s" x="360" y="254" text-anchor="middle">Netty 长连接 + 二进制序列化</text>
</svg>
</div>
<figcaption>注册中心只管「通讯录」，真正的调用是消费者直接连提供者。所以注册中心挂了，已经在跑的调用不受影响（消费者内存里有地址列表），只是新上线、下线的机器感知不到。</figcaption>
</figure>

### ZooKeeper 是什么

一个小型的、强一致的**树形存储**：像文件系统一样按路径存数据，每个节点叫 znode，最多存 1MB。它专门存「谁在线、配置是什么、谁拿到了锁」这类协调信息，不是用来存业务数据的。它能当注册中心，靠的是三个特性：

- **临时节点**：客户端和 ZooKeeper 之间有一个会话（session，一条靠心跳维持的长连接），会话断开并超时后，这个客户端创建的临时节点自动删除。Dubbo 提供者注册的就是临时节点，所以机器宕机后地址会自动消失。
- **顺序节点**：创建时自动在名字后面加一个递增的 10 位编号，用来做分布式锁、排队。
- **监听（Watcher）**：客户端监听某个节点，节点变化时 ZooKeeper 主动通知。普通监听是一次性的，触发一次后要重新注册；3.6 起增加了不会自动失效的持久监听。

Dubbo 在 ZooKeeper 里的目录：

```text
/dubbo
  └─ 接口全名（如 com.example.OrderService）
       ├─ providers      提供者地址（临时节点），消费者监听这里
       ├─ consumers      消费者地址
       ├─ configurators  动态配置（如临时改权重、超时）
       └─ routers        路由规则
```

### ZooKeeper 集群：谁说了算

- 角色：**Leader** 处理所有写请求；**Follower** 处理读请求、参与投票；**Observer** 只处理读、不投票，用来扩展读能力。
- 写：Leader 把写请求发给 Follower，**超过半数确认**才算成功（这套协议叫 ZAB）。所以集群一般是奇数台：3 台能挂 1 台，5 台能挂 2 台；4 台也只能挂 1 台，多一台白费。
- Leader 挂了：剩下的机器重新选举，选举期间不能写。也就是说 ZooKeeper 宁可短时间不可用，也要保证数据一致。
- 用 CAP 说（网络断开时，「一致性」和「可用性」只能保一个）：ZooKeeper 是 **CP**；Eureka 是 **AP**（宁可返回旧地址也保证能查）。

### 一次 Dubbo 调用经过什么

1. 消费者拿到的是代理对象，调方法实际进了代理；
2. **Directory**：从注册中心同步来的提供者列表；
3. **Router**：按路由规则过滤（比如只调同机房的）；
4. **LoadBalance**：从剩下的里挑一台，**默认加权随机**；
5. **Cluster 容错**：调失败了怎么办，**默认 failover**——换一台重试，默认重试 2 次（加第一次共 3 次）；
6. **协议层**：dubbo 协议，单一长连接，底层用 Netty 传输，参数序列化成二进制；
7. **提供者**：Netty 收到请求，交给业务线程池执行（Dubbo 2.6.2 默认 fixed 200 个线程、不排队，满了报 `Thread pool is EXHAUSTED!`），结果原路返回。2.6.2 默认超时 1000 毫秒。

| 容错策略 | 失败后怎么办 | 适合 |
|---|---|---|
| failover（默认） | 换一台重试，`retries` 控制次数 | 读操作 |
| failfast | 只调一次，失败立即报错 | 不能重复执行的写操作 |
| failsafe | 出错就忽略，只记日志 | 写审计日志这类不重要的 |
| failback | 失败的请求记下来，后台定时重发 | 消息通知 |
| forking | 同时调多台，一个成功就返回 | 实时性要求高的读，费资源 |
| broadcast | 逐个调所有提供者，任意一台失败就报错 | 通知所有机器刷新本地缓存 |

### 写操作为什么要把 retries 配成 0

默认的 failover 会在超时后换一台再调。但超时不等于失败：第一次可能已经执行成功，只是响应慢了，这时重试就会重复执行，比如重复下单、重复扣款。所以写操作要么配 `retries="0"`（或用 failfast），要么接口本身做幂等。

### ZooKeeper 怎么做分布式锁

1. 所有抢锁的客户端在 `/lock` 下创建「临时 + 顺序」节点：`lock-0000000001`、`…02`、`…03`；
2. 编号最小的拿到锁；
3. 其他人**只监听比自己小一号的节点**。如果所有人都监听最小的那个，锁一释放所有人同时被唤醒去抢，白白给 ZooKeeper 造成一波请求高峰；
4. 释放锁就是删掉自己的节点；持锁的进程挂了，会话超时后临时节点自动删除，不会出现锁永远不释放。

Java 里直接用 Curator 的 `InterProcessMutex`。和 Redis 锁比：ZooKeeper 锁不靠过期时间，更可靠，但每次加锁都要写 ZooKeeper、走一遍过半确认，性能比 Redis 低；Redis 锁快，但要处理过期时间和续期。

### 常见问题

#### Dubbo 一次调用的完整过程？

按上面「一次 Dubbo 调用经过什么」的 7 步讲，边讲边画第一张图。重点说清三件事：注册中心只管地址、调用是直连；默认加权随机 + failover 重试 2 次；提供者用线程池处理，满了直接拒绝。

#### 注册中心挂了，服务还能调吗？

能。消费者内存里有一份提供者列表，调用是直连提供者的，不经过注册中心。影响是：新上线的机器发现不了，下线的机器也不会被剔除（只能靠调用失败重试和连接断开检测）。

#### Dubbo 的负载均衡策略有哪些？默认哪个？

默认**加权随机**（random）。其他：加权轮询（roundrobin）、最少活跃（leastactive，正在处理的请求少的优先，慢机器自然少分）、最短响应（shortestresponse）、一致性哈希（consistenthash，同样的参数总落到同一台）；Dubbo 3 还有 p2c、adaptive（随机挑两台选负载低的）。

#### Dubbo 集群容错有哪些？写操作为什么配 retries="0"？

见上面的容错策略表。一句话：默认 failover 会重试，写操作重试可能重复执行，所以写操作配 0 或者做幂等。

#### 提供者宕机，消费者怎么知道？

提供者注册的是临时节点。宕机后它和 ZooKeeper 的会话没了心跳，超过会话超时时间后 ZooKeeper 删除这个临时节点，触发 `providers` 目录的监听，通知所有消费者，消费者更新本地列表。

**追问**：会话超时之前那段时间呢？→ 消费者还会调到这台挂掉的机器，靠 failover 换一台重试，或者 Dubbo 自己的连接心跳发现连接断开后不再选它。

#### ZooKeeper 为什么用奇数台？Leader 挂了怎么办？

写入要超过半数确认才成功，集群要超过半数机器活着才能工作。3 台能挂 1 台，4 台也只能挂 1 台，所以多出的那台没有提高容错能力。Leader 挂了，剩下的机器重新选举，选出新 Leader 之前不能写。

#### ZooKeeper、Nacos、Eureka 有什么区别？

ZooKeeper 是 CP，保证一致，选举时不可写；Eureka 是 AP，保证能用，可能返回旧数据；Nacos 除了注册中心还自带配置中心。

#### Dubbo 和 Spring Cloud（OpenFeign）有什么区别？

Dubbo 是 RPC 框架：长连接、二进制协议，按 Java 接口调用，性能好；OpenFeign 走 HTTP + JSON，通用、跨语言、好调试，但性能差一些。Dubbo 3 新增了 Triple 协议（基于 HTTP/2、兼容 gRPC），两边的界限在变模糊。

#### Dubbo 的 SPI 是什么？

SPI 是一种「接口由框架定义、实现由配置文件指定」的扩展机制。Java 自带的 `ServiceLoader` 会一次加载全部实现；Dubbo 自己实现了一套，按名字加载：在 `META-INF/dubbo/` 下以接口全名命名的文件里写 `名字=实现类`，比如 `random=…RandomLoadBalance`。还支持运行时按 URL 参数选实现（自适应扩展）。负载均衡、协议、序列化、线程池都是这样扩展的。

## 六、WebSocket 和 Netty

### 先看要解决什么问题

行情 App 里股价每秒在跳，直播间弹幕不停地刷，都需要**服务器主动把数据推给用户**。HTTP 是「客户端问一句、服务器答一句」，服务器没法主动开口。有四种办法：

| 办法 | 怎么做 | 问题 |
|---|---|---|
| 短轮询 | 浏览器每隔 1 秒发一次请求问「有新数据吗」 | 大部分请求白问；最多晚 1 秒；每次都带完整的 HTTP 头 |
| 长轮询 | 请求发过去，服务器有数据才返回，没数据就挂着等（比如 30 秒）；返回后客户端马上再发 | 比短轮询省，但每条消息还是一次请求 |
| SSE | 一个 HTTP 请求，服务器不断往回写（`text/event-stream`） | 只能服务器 → 浏览器单向。AI 对话逐字输出常用它（Spring 里是 `SseEmitter`） |
| WebSocket | 先用 HTTP 握手，然后升级成一条双向长连接，双方随时互发 | 要自己管连接、心跳、多台机器 |

### 握手：从 HTTP「升级」过来

```text
客户端 → 服务器
GET /ws/quote HTTP/1.1
Host: example.com
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==
Sec-WebSocket-Version: 13

服务器 → 客户端
HTTP/1.1 101 Switching Protocols
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=
```

- **101** 表示「同意换协议」。之后这条 TCP 连接上跑的就不是 HTTP 了，而是 WebSocket 的「帧」。
- **Sec-WebSocket-Accept** = Base64(SHA-1(Key + 固定字符串 `258EAFA5-E914-47DA-95CA-C5AB0DC85B11`))。作用是证明对面真的懂 WebSocket，不是一个普通 HTTP 服务器误回了响应。**它不是加密，也不是鉴权**。
- **帧**：每条消息被包成帧，帧头里写着类型：文本、二进制、关闭、ping、pong（ping / pong 用来做心跳）。浏览器发给服务器的帧必须加掩码（用随机 4 字节把数据异或一遍，防止中间的代理服务器被构造的数据骗去缓存错误内容）；服务器发出的帧不加。

### Java 里怎么写

1. **Spring WebSocket**：`@EnableWebSocket` + 继承 `TextWebSocketHandler`，重写连上、收到消息、断开三个方法；在 `HandshakeInterceptor` 里做握手鉴权。
2. **Spring + STOMP**：在 WebSocket 上再加一层「订阅 / 发布」协议。前端订阅 `/topic/stock/600519`，后端 `convertAndSend` 到这个地址，适合按主题订阅。
3. **Netty**：高并发推送一般用它。

```java
ch.pipeline()
  .addLast(new HttpServerCodec())                    // HTTP 编解码（握手阶段是 HTTP）
  .addLast(new HttpObjectAggregator(65536))          // 把分段的 HTTP 消息拼成完整的
  .addLast(new IdleStateHandler(60, 0, 0))           // 60 秒没收到数据，触发空闲事件
  .addLast(new WebSocketServerProtocolHandler("/ws")) // 完成握手，处理 ping / pong / close
  .addLast(new QuoteFrameHandler());                 // 自己写：处理订阅、推送、空闲时关连接
```

### 上线要处理的五件事（面试重点）

1. **心跳**：手机切到后台、断网时，TCP 不一定能及时发现连接已断。客户端每 20–30 秒发一次 ping，服务端用 `IdleStateHandler` 检测，超过一定时间没收到任何数据就关掉连接。前面有 Nginx 的话，Nginx 默认 60 秒没数据就断开连接（`proxy_read_timeout`），心跳间隔必须小于它；Nginx 还要配 `Upgrade` 和 `Connection` 头才能把握手转发过去。
2. **鉴权**：握手时校验 token（放在 URL 参数或 Cookie 里，浏览器的 WebSocket API 不能自定义请求头），不通过直接拒绝握手。握手时解析出 userId，存到连接的属性里，后面每条消息都知道是谁发的。
3. **多台机器怎么推**：见下图。
4. **断线重连和补数据**：客户端按 1、2、4、8 秒递增的间隔重连；重连后先拉一次最新快照，再接着收推送；不能丢的消息带递增序号，客户端发现序号断了就去补。
5. **慢客户端**：有的用户网络差，服务器往他那写的数据堆在内存里越积越多。Netty 里用 `channel.isWritable()` 判断，写不动时行情这种数据只保留最新一条；聊天类消息就断开让他重连后补。

<figure class="fig">
<div class="fig-box">
<svg viewBox="0 0 720 292" role="img" aria-label="多台推送机器：消息广播到每台，每台只推给本机连接">
<defs><marker id="iq2-a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah" d="M0 0L10 5L0 10z"/></marker><marker id="iq2-p" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah-pri" d="M0 0L10 5L0 10z"/></marker><marker id="iq2-s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah-sec" d="M0 0L10 5L0 10z"/></marker></defs>
<rect class="bx-off" x="15.2" y="110" width="142.1" height="64" rx="8"/>
<text class="t-b" x="86.2" y="137" text-anchor="middle">新消息</text>
<text class="t-s" x="86.2" y="158" text-anchor="middle">行情 / 弹幕 / 礼物</text>
<rect class="bx-heap" x="214.1" y="110" width="151.6" height="64" rx="8"/>
<text class="t-b" x="289.9" y="137" text-anchor="middle">广播通道</text>
<text class="t-s" x="289.9" y="158" text-anchor="middle">Redis 发布订阅 或 MQ</text>
<rect class="bx" x="422.5" y="30" width="151.6" height="74" rx="8"/>
<text class="t-b" x="498.3" y="58" text-anchor="middle">推送机器 1</text>
<text class="t-s" x="498.3" y="80" text-anchor="middle">本机连接：A、B</text>
<rect class="bx" x="422.5" y="186" width="151.6" height="74" rx="8"/>
<text class="t-b" x="498.3" y="214" text-anchor="middle">推送机器 2</text>
<text class="t-s" x="498.3" y="236" text-anchor="middle">本机连接：C</text>
<rect class="bx-heap" x="625.3" y="24" width="79.6" height="32" rx="8"/>
<text x="665.1" y="45" text-anchor="middle">用户 A</text>
<rect class="bx-heap" x="625.3" y="78" width="79.6" height="32" rx="8"/>
<text x="665.1" y="99" text-anchor="middle">用户 B</text>
<rect class="bx-heap" x="625.3" y="207" width="79.6" height="32" rx="8"/>
<text x="665.1" y="228" text-anchor="middle">用户 C</text>
<path class="ln" d="M159.2 142L212.2 142" marker-end="url(#iq2-a)"/>
<text x="185.7" y="100" text-anchor="middle">① 发布一次</text>
<path class="ln" d="M367.6 130L420.6 72" marker-end="url(#iq2-a)"/>
<path class="ln" d="M367.6 154L420.6 212" marker-end="url(#iq2-a)"/>
<text x="373.3" y="146">② 每台都收到</text>
<path class="ln ln-pri" d="M576 58L623.4 42" marker-end="url(#iq2-p)"/>
<path class="ln ln-pri" d="M576 80L623.4 93" marker-end="url(#iq2-p)"/>
<path class="ln ln-pri" d="M576 223L623.4 223" marker-end="url(#iq2-p)"/>
<text class="t-pri" x="568.4" y="282" text-anchor="middle">③ 只推给本机订阅了的连接</text>
</svg>
</div>
<figcaption>每台推送机器只管自己身上的连接。一对多的消息（行情、弹幕）用广播；一对一的消息（私信、个人通知）可以在 Redis 里记「用户 → 连在哪台机器」，只转给那一台。</figcaption>
</figure>

### 常见问题

#### WebSocket 和 HTTP 是什么关系？握手过程？

WebSocket 借 HTTP 握手：客户端发带 `Upgrade: websocket` 和 `Sec-WebSocket-Key` 的 GET 请求，服务器返回 101 和 `Sec-WebSocket-Accept`，之后同一条 TCP 连接改用 WebSocket 帧双向通信，不再是 HTTP。所以它能走 80 / 443 端口、能被 Nginx 代理。

#### WebSocket、SSE、长轮询怎么选？

只需要服务器往下推（行情、通知、AI 逐字输出）：SSE 够用，本身就是 HTTP，对代理和网关更友好，浏览器断了会自动重连。需要双向频繁交互（弹幕、聊天、客户端要不断改订阅）：WebSocket。长轮询是兼容老环境的保底办法。

#### WebSocket 服务部署多台，消息怎么推给连在别的机器上的用户？

连接是有状态的，用户 A 的连接只在机器 1 上。两种办法：① **广播**：消息发到 Redis 发布订阅或 MQ 的 fanout 交换机，每台机器都收到，各自推给本机上订阅了的连接（见上图），适合行情、直播间这种一对多；② **路由表**：Redis 里存「userId → 机器」，消息只转给那一台，适合私信、个人通知。

#### 怎么知道连接已经断了？心跳怎么做？

客户端定时发 ping（或自定义的心跳消息），服务端用 `IdleStateHandler` 检测读空闲，超过约 2–3 个心跳周期没收到数据就关闭连接、清理订阅。心跳间隔要小于 Nginx 等代理的读超时（Nginx 默认 60 秒）。

#### 单机能撑多少连接？受什么限制？

每个连接占一个文件句柄（要调大 `ulimit -n`）和一些内存（读写缓冲区）；连接本身闲着时几乎不占 CPU，推送量大才占。具体多少要压测，和每秒推多少消息关系很大，不要背一个数字。服务端端口不是限制：一个监听端口能接很多连接，连接靠「双方 IP + 双方端口」四个值区分。

#### Netty 为什么适合做推送服务？

少量线程管大量连接（主从 Reactor：一组线程专门接新连接，一组线程负责已有连接的读写，每个线程用 IO 多路复用同时盯很多连接）；直接内存和零拷贝减少复制；内存池减少 GC；自带 WebSocket 编解码、空闲检测、粘包拆包处理。

## 七、Elasticsearch

### 先看要解决什么问题

用户在 App 里搜「华为手机」。MySQL 只能写 `WHERE title LIKE '%华为手机%'`：前面带 `%` 用不上索引，要全表扫；而且「华为的手机」「手机 华为」都搜不到，结果也没法按「有多相关」排序。

### 原理：倒排索引

三条文档：①「华为手机降价」②「苹果手机发布」③「华为平板上市」。先切词，再记下每个词出现在哪些文档里：

| 词 | 出现在哪些文档 |
|---|---|
| 华为 | ①、③ |
| 手机 | ①、② |
| 降价 / 苹果 / 发布 / 平板 / 上市 | ① / ② / ② / ③ / ③ |

搜「华为手机」→ 切成「华为」「手机」→ 查表得 {①③} 和 {①②} → 文档 ① 两个词都中，排最前。**从文档找词**叫正排（像 MySQL 一行行看）；**从词找文档**叫倒排（像书后面的索引页）。中文切词要装分词插件（常用 IK），默认的分词器会把中文切成一个个单字。

### 和 MySQL 的概念对照

| ES | 约等于 MySQL | 说明 |
|---|---|---|
| 索引（index） | 表 |  |
| 文档（document） | 一行 | JSON 格式 |
| 映射（mapping） | 表结构 | 定义字段类型。**text** 会切词，用来全文搜；**keyword** 不切词，用来精确匹配、排序、分组统计 |
| 分片（shard） | 分表 | 一个索引拆成几份放在不同机器上；主分片数建好后不能直接改，要重建索引 |
| 副本（replica） | 从库 | 分片的复制，既防丢数据，又能分担查询 |

### 为什么写进去不能马上搜到

写入 → 先进内存缓冲区，同时写 translog（类似 MySQL 的 redo log，防止宕机丢数据）→ **refresh**：把缓冲区生成一个新的小索引文件（segment），这时才能搜到 → **flush**：把 segment 真正写入磁盘、清空 translog。refresh 默认每 1 秒一次（只对最近 30 秒内被搜过的索引自动做），所以写进去大约 1 秒后才能搜到，叫「近实时」。批量导数据时可以先把 `refresh_interval` 设成 `-1`，导完改回 `1s`。

### MySQL 的数据怎么同步到 ES

1. 代码里双写：简单，但一边成功一边失败就不一致；
2. 写 MySQL 后发 MQ，消费者写 ES：解耦，失败可以重试；
3. 监听 binlog 写 ES（Canal 伪装成 MySQL 从库读 binlog）：业务代码不用改，最常用。

思路和 Redis 缓存一致性一样。证券业务里 ES 会用在：股票代码 / 名称 / 拼音首字母搜索、资讯和公告全文检索、日志检索（ELK：Elasticsearch + Logstash + Kibana）。

### 常见问题

#### ES 为什么搜索快？倒排索引是什么？

写入时先把文本切成词，建一张「词 → 包含这个词的文档列表」的表。查询时把搜索词也切开，按词直接查到文档，再合并、按相关度打分排序，不用逐行扫描。

#### ES 写进去为什么不能马上搜到？

新数据先在内存缓冲区里，refresh 生成 segment 后才能被搜到，默认每秒一次，所以是近实时。要马上可见可以在写入时带 `refresh=wait_for`，但频繁 refresh 会拖慢写入。

#### ES 深分页怎么办？

`from + size` 默认不能超过 10000（`index.max_result_window`）。越往后越慢，因为每个分片都要取出 from + size 条交给协调节点汇总排序。往后翻用 `search_after`：带上上一页最后一条的排序值往后取，适合「下一页」式翻页；导出全量用 PIT（时间点快照）+ `search_after`。

#### text 和 keyword 的区别？

text 写入时会切词，用于全文搜索，不能直接用来排序和分组；keyword 整体作为一个词存，用于精确匹配（状态、股票代码）、排序、分组统计。一个字段可以同时有两种（多字段映射）。

#### ES 集群里一次查询怎么执行？

请求到任意一个节点（这次的协调节点）→ 转给每个分片（主分片或副本都行）→ 每个分片查出自己的前 N 条的 id 和分数（query 阶段）→ 协调节点汇总排序取前 N → 再去对应分片拿完整文档（fetch 阶段）→ 返回。

## 八、MongoDB

**是什么**：文档数据库。一条记录是一个类似 JSON 的文档（底层存成二进制格式 BSON），同一个集合（collection，相当于表）里的文档字段可以不一样，不用提前建表结构。

### 原理要点

- **存储引擎**：默认 WiredTiger，文档级别的并发控制（两个人改不同的文档互不影响），自带压缩。
- **索引**：B 树，支持单字段、复合、TTL 索引（到时间自动删文档，适合日志、验证码）。复合索引同样遵守最左前缀。
- **副本集**：一主多从，写都到主节点，主挂了从节点自动选出新主；默认读主，可以配置读从。
- **分片集群**：mongos（路由）+ 配置服务器（记录数据在哪个分片）+ 多个分片，按分片键把数据分开；分片键选不好会让数据或请求集中到一台。
- **事务**：单个文档的写入本来就是原子的；多文档事务副本集 4.0 起、分片集群 4.2 起支持，但开销大，设计上尽量把要一起改的数据放进同一个文档。

### 和 MySQL 对比

|  | MySQL | MongoDB |
|---|---|---|
| 结构 | 先建表，字段固定 | 不用建表，每个文档字段可以不同 |
| 关联 | JOIN 成熟 | 推荐把相关数据嵌在一个文档里；`$lookup` 能关联但不擅长 |
| 事务 | 成熟 | 支持多文档事务，开销大 |
| 扩展 | 分库分表靠中间件 | 自带分片 |
| 适合 | 交易、账务、强关联数据 | 结构多变、整块读写：原始报文、日志、资讯文章、直播聊天记录 |

### 常见问题

#### MongoDB 和 MySQL 怎么选？

钱、订单、需要多表关联和强事务的放 MySQL；结构多变、整块读写、量大、不需要复杂关联的放 MongoDB。比如对接多家合作方时，各家推来的原始报文格式不同、只按订单号整块读，就适合放 MongoDB。

#### 副本集主节点挂了会怎样？

剩下的节点自动选出新主，选举期间不能写，驱动会自动连到新主。写入时设置 `writeConcern: majority`（写到多数节点才算成功），可以避免主节点挂掉时刚写的数据丢失。

## 九、Memcached 和一致性哈希

**是什么**：纯内存的键值缓存，值只能是字符串（字节），不持久化，重启数据全没。比 Redis 早，现在新项目基本都用 Redis。

|  | Memcached | Redis |
|---|---|---|
| 数据结构 | 只有字符串 | 字符串、哈希、列表、集合、有序集合等 |
| 持久化 | 没有 | RDB、AOF |
| 线程 | 多线程 | 执行命令是单线程（6.0 起网络读写可以多线程） |
| 集群 | 服务端之间互不通信，客户端用一致性哈希决定放哪台 | 主从、哨兵、官方 Cluster（16384 个槽） |
| 单个值大小 | 默认最大 1MB（`-I` 参数可调） | 字符串最大 512MB |
| 内存管理 | Slab：预先把内存切成大小不同的格子，按值的大小放进合适的格子，没有碎片但有浪费 | 按需分配 |
| 适合 | 简单、超大并发的纯缓存 | 缓存，以及计数、排行榜、锁、延迟队列等 |

### 一致性哈希（Memcached 客户端、Dubbo 的 consistenthash、Nginx 都会用）

**问题**：缓存放在 N 台机器上，最简单的是 `hash(key) % N`。加一台机器，N 变了，几乎所有 key 都换了位置，缓存等于全部失效，请求全落到数据库。

**做法**：把哈希值想成一个圆环（0 到 2³²−1），机器按自己的哈希值放到环上，key 也算出哈希放到环上，顺时针碰到的第一台机器就是它的归属。加一台机器只影响它前面那一小段 key。机器少的时候分布不均，就给每台机器在环上放很多「虚拟节点」，让分布更均匀。

### 常见问题

#### Memcached 和 Redis 的区别？为什么现在都用 Redis？

按上表说数据结构、持久化、线程、集群四点。现在都用 Redis，是因为它数据结构丰富，一个组件能做缓存、计数、排行榜、分布式锁，还能持久化、有官方集群；Memcached 的优势（多线程、简单）在大多数业务里不是瓶颈。

#### 一致性哈希是什么？解决什么问题？

见上面。一句话：加减机器时只有一小部分 key 需要换位置，而不是全部；用虚拟节点解决分布不均。

## 十、Oracle 和 MySQL 的差别

SQL 和调优思路和 MySQL 相通，主要差别是这几点：

|  | MySQL（InnoDB） | Oracle |
|---|---|---|
| 自增主键 | `AUTO_INCREMENT` | 序列 `SEQUENCE`（`seq.NEXTVAL`）；12c 起也支持 IDENTITY 列 |
| 分页 | `LIMIT 10, 20` | 老写法用 `ROWNUM` 嵌套子查询；12c 起 `OFFSET 10 ROWS FETCH NEXT 20 ROWS ONLY` |
| 默认隔离级别 | 可重复读 | 读已提交 |
| 空字符串 | `''` 和 NULL 不同 | `''` 当作 NULL |
| 常见函数和类型 | `IFNULL`、`VARCHAR` | `NVL`、`VARCHAR2` |
| 不查表 | `SELECT 1` | `SELECT 1 FROM DUAL` |
| 看执行计划 | `EXPLAIN` | `EXPLAIN PLAN FOR …` 再用 `DBMS_XPLAN` 查看；整库性能看 AWR 报告 |
| 读不加锁 | undo log + MVCC | 同样靠 undo 保存旧版本实现 |
| 费用 | 社区版免费 | 商业收费，金融、证券的老系统用得多 |

```sql
-- Oracle 11g 及以前：按时间倒序取第 11–30 行
SELECT * FROM (
  SELECT t.*, ROWNUM rn FROM (
    SELECT * FROM orders ORDER BY create_time DESC
  ) t WHERE ROWNUM <= 30
) WHERE rn > 10;
```

为什么要套三层：`ROWNUM` 是结果的行号，在排序**之前**就分配了，所以要先在最里层排好序；而且 `WHERE ROWNUM > 10` 永远查不到数据（第一行的 ROWNUM 是 1，不满足被丢掉，下一行又成了 1），所以要先在中间层把行号存成 `rn`，外层再过滤。

### 常见问题

#### Oracle 和 MySQL 有什么区别？

挑表里四五点说：自增用序列、分页用 ROWNUM、默认隔离级别是读已提交、空字符串等于 NULL、商业数据库。再补一句「SQL 优化思路相通：看执行计划、建合适的索引、避免全表扫描」。

#### Oracle 分页怎么写？为什么要嵌套？

见上面的 SQL 和解释。

## 十一、负载均衡和分布式

### 负载均衡分几层

| 层 | 例子 | 按什么转发 |
|---|---|---|
| DNS | 一个域名解析到多个 IP | 按地域、运营商 |
| 四层 | LVS、云厂商的负载均衡 | 只看 IP 和端口，不看内容，快 |
| 七层 | Nginx | 能看 HTTP 内容，按路径、请求头转发 |
| 服务内部 | Dubbo、Spring Cloud LoadBalancer | 调用方自己从地址列表里挑 |

| 算法 | 说明 | 谁的默认 / 用在哪 |
|---|---|---|
| 加权轮询 | 按顺序轮流，权重高的多分 | Nginx 默认 |
| 加权随机 | 按权重随机挑 | Dubbo 默认 |
| 最少活跃 / 最少连接 | 谁手上正在处理的请求少给谁，慢机器自然少分 | Dubbo leastactive、Nginx least_conn |
| 一致性哈希 / IP 哈希 | 同一个参数或同一个 IP 固定落到同一台 | 有状态的场景：本地缓存、会话 |

### 分布式事务

| 方案 | 怎么做 | 特点 |
|---|---|---|
| 2PC / XA | 协调者先让各方「准备」，都说可以再一起「提交」 | 强一致，但锁资源时间长、协调者挂了就卡住，互联网业务少用 |
| TCC | 每个操作写三个方法：Try 预留（冻结余额）、Confirm 确认、Cancel 释放 | 一致性好，代码量大；要处理「Try 没执行就收到 Cancel」和「Cancel 先到、Try 后到」两种乱序 |
| 本地消息表 | 业务数据和「待发消息」在同一个本地事务里写库，定时任务把消息发出去直到成功 | 简单可靠，最常用 |
| MQ 事务消息 | 先发「半消息」，本地事务成功后再确认投递（RocketMQ 支持） | 依赖 MQ 的能力 |
| 最大努力通知 + 对账 | 回调通知 + 主动查询 + 每日对账 | 和第三方支付对接的标准做法 |
| Seata AT | 框架自动记录修改前的数据，失败时自动回滚 | 对代码改动小 |

和第三方支付、放款平台对接时最常见的是「最大努力通知 + 对账」：对方异步回调，回调可能丢 → 定时任务主动查订单状态补上；对方重复回调 → 带状态条件的 UPDATE 保证只改一次；最后每天和对方对账。

### 幂等（重试、重复消息、重复点击都会造成重复请求）

- 唯一索引：业务流水号建唯一索引，重复插入直接报错；
- 状态机：`UPDATE … SET status = '成功' WHERE id = ? AND status = '处理中'`，影响 0 行说明处理过了；
- 防重 token：进页面先领一个 token，提交时带上，服务端从 Redis 删除成功才处理（防表单重复提交）；
- 带条件扣减：`UPDATE account SET balance = balance - 100 WHERE id = ? AND balance >= 100`。

### 分布式 ID 和 CAP

**雪花算法**（64 位）：1 位符号 + 41 位毫秒时间戳 + 10 位机器号 + 12 位序号。同一台机器同一毫秒能生成 4096 个，整体按时间递增，适合做主键。问题：服务器时钟往回调会生成重复 ID，检测到就等待或报错。其他方案：数据库号段（一次领 1000 个号在内存里发，如美团 Leaf）、Redis `INCR`。

**CAP**：机器之间网络断开时，一致性（C，所有节点数据一样）和可用性（A，每个请求都有响应）只能保一个；P（容忍网络断开）是分布式系统的前提。ZooKeeper 选 CP，Eureka 选 AP。BASE 是 AP 的做法：基本可用、允许短暂不一致、最终一致。

### 常见问题

#### 分布式事务有哪些方案？怎么选？

先说表里几种，再说怎么选：对接第三方用「主动查询 + 回调 + 对账」，也就是最大努力通知；内部服务之间用本地消息表 + 幂等。理由：和第三方之间本来就做不了强一致，靠补偿和对账达到最终一致；强一致的 2PC 锁资源时间长，互联网业务很少用。

#### 接口幂等怎么做？

见上面四种。按场景选：创建类用唯一索引，状态变更用状态机条件更新，扣减类用带条件的 UPDATE，前端重复提交用 token。

#### 负载均衡有哪些算法？Nginx 和 Dubbo 默认各是什么？

见上表。Nginx 默认加权轮询，Dubbo 默认加权随机。

#### 雪花算法的结构和问题？

见上面。追问机器号怎么分配：配置文件写死、启动时从 ZooKeeper 顺序节点或 Redis 领一个。

## 十二、前端基础

### 什么是跨域？怎么解决？

浏览器的同源策略：协议、域名、端口三个都相同才算同源，不同源的 Ajax 请求，浏览器会拦下响应不给页面用。解决：

1. **CORS**：服务端在响应头里返回 `Access-Control-Allow-Origin`（允许哪些来源）等。非简单请求（比如带 JSON 请求体、自定义请求头）浏览器会先发一个 OPTIONS「预检」请求问服务器允不允许。Spring 里用 `@CrossOrigin` 或全局的 `addCorsMappings`。
2. **Nginx 反向代理**：前端页面和接口挂在同一个域名下，就不存在跨域。
3. **JSONP**：利用 `<script>` 标签不受同源限制，只支持 GET，老办法。

注意：跨域是浏览器的限制，服务器之间互相调用没有跨域问题。

### Ajax 是什么？

页面不刷新，用 JavaScript 在后台发 HTTP 请求，拿到数据后只更新页面的一部分。原生是 `XMLHttpRequest`，现在多用 `fetch` 或 axios；jQuery 的 `$.ajax` 是对 `XMLHttpRequest` 的封装。

### Vue 的核心思想？v-if 和 v-show、computed 和 watch 的区别？

**数据驱动**：改数据，页面自动更新，不用自己操作页面元素（jQuery 是自己找到元素去改）。

`v-if` 条件不满足时元素根本不生成，切换开销大；`v-show` 只是隐藏（`display: none`），适合频繁切换。`computed` 是根据别的数据算出来的值，有缓存，依赖不变不重算；`watch` 是数据变了去做一件事（比如发请求）。Vue 2 用 `Object.defineProperty` 拦截属性读写，Vue 3 改用 `Proxy`，能监听新增属性和数组下标。

### Cookie、Session、Token 的区别？

Cookie 是浏览器存的小数据，每次请求自动带上；Session 是服务端存的会话数据，靠 Cookie 里的 sessionId 找到，多台服务器时要共享（Spring Session + Redis）；Token（如 JWT）把用户信息签名后交给客户端，服务端只验签不用存，适合 App 和多服务，缺点是发出去在过期前收不回，要配合短有效期 + 刷新 token 或黑名单。

### HTML5 有哪些新东西？

语义标签（header、nav、article）、video / audio、canvas 画图、localStorage / sessionStorage 本地存储、WebSocket、地理定位。和后端关系最大的是 WebSocket 和本地存储。

## 十三、证券行情数据

### 几个词

| 词 | 意思 |
|---|---|
| 行情 | 股票价格、成交量等实时变化的数据 |
| 盘口 / 五档 | 当前挂着的买单和卖单：买一到买五（出价最高的 5 个价位）、卖一到卖五，每档有价格和数量 |
| 快照 | 某一时刻一只股票的完整状态：最新价、今开、最高、最低、成交量、成交额、五档盘口…… |
| 逐笔成交 / 逐笔委托 | 每一笔成交、每一笔下单和撤单的明细 |
| K 线 | 一段时间（1 分钟、日、周）的开盘价、最高价、最低价、收盘价，再加成交量 |
| 分时图 | 当天每分钟的价格连成的线 |
| 复权 | 分红、送股后股价会突然「掉一截」，K 线不连续；前复权 / 后复权是把历史价格按比例调整，让走势连续 |
| Level-1 / Level-2 | 两档行情服务：Level-1 是基础行情（五档盘口）；Level-2 有十档盘口、逐笔成交、逐笔委托，数据量大很多，单独收费 |

### 交易规则（决定数据什么时候来、来多少）

- **交易时间**：9:15–9:25 开盘集合竞价（9:20 后不能撤单）；9:30–11:30、13:00–14:57 连续竞价；14:57–15:00 收盘集合竞价。流量集中在交易时段，开盘那一下最大。
- **集合竞价**：一段时间内收集所有买卖单，最后按能让成交量最大的一个价格一次性撮合；**连续竞价**：价格优先、时间优先，来一单撮合一单。
- **T+1**：今天买的股票明天才能卖。
- **涨跌幅限制**：主板 10%（风险警示股票原来是 5%，2026-07-06 起也改成 10%）；创业板、科创板 20%；北交所 30%。

### 行情数据的特点（设计系统时要用上）

1. **只关心最新**：新价格来了，旧的就没用了。推送时可以合并（200 毫秒内同一只股票变了几次只推最后一次）、可以丢中间值。这和订单、资金消息正好相反——那些一条都不能丢。
2. **高峰集中**：开盘、收盘、大行情时流量是平时的好几倍，要按高峰设计。
3. **一对多**：一只热门股可能几十万人同时在看，同一份数据推给很多人 → 按股票订阅、广播。
4. **按时间追加**：数据按时间不断追加、基本不改，查询多是「某只股票某段时间」→ 按股票代码 + 日期组织；历史数据用列式存储或时序数据库（ClickHouse、TDengine 等），最新快照放 Redis。

<figure class="fig">
<div class="fig-box">
<svg viewBox="0 0 720 278" role="img" aria-label="行情系统链路：接收、Kafka、计算、存储、推送">
<defs><marker id="iq3-a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah" d="M0 0L10 5L0 10z"/></marker><marker id="iq3-p" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah-pri" d="M0 0L10 5L0 10z"/></marker><marker id="iq3-s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah-sec" d="M0 0L10 5L0 10z"/></marker></defs>
<rect class="bx-off" x="9.5" y="20" width="142.1" height="64" rx="8"/>
<text class="t-b" x="80.5" y="47" text-anchor="middle">交易所 / 行情商</text>
<text class="t-s" x="80.5" y="68" text-anchor="middle">二进制行情数据</text>
<rect class="bx" x="189.5" y="20" width="142.1" height="64" rx="8"/>
<text class="t-b" x="260.5" y="47" text-anchor="middle">行情接收</text>
<text class="t-s" x="260.5" y="68" text-anchor="middle">解码、校验、去重</text>
<rect class="bx-heap" x="369.5" y="20" width="142.1" height="64" rx="8"/>
<text class="t-b" x="440.5" y="47" text-anchor="middle">Kafka</text>
<text class="t-s" x="440.5" y="68" text-anchor="middle">按股票代码分区</text>
<rect class="bx" x="549.5" y="20" width="157.3" height="64" rx="8"/>
<text class="t-b" x="628.1" y="47" text-anchor="middle">计算</text>
<text class="t-s" x="628.1" y="68" text-anchor="middle">K 线、涨跌幅、指标</text>
<path class="ln" d="M153.5 52L187.6 52" marker-end="url(#iq3-a)"/>
<path class="ln" d="M333.5 52L367.6 52" marker-end="url(#iq3-a)"/>
<path class="ln" d="M513.5 52L547.6 52" marker-end="url(#iq3-a)"/>
<rect class="bx" x="549.5" y="176" width="157.3" height="70" rx="8"/>
<text class="t-b" x="628.1" y="202" text-anchor="middle">存储</text>
<text class="t-s" x="628.1" y="222" text-anchor="middle">Redis：最新快照</text>
<text class="t-s" x="628.1" y="238" text-anchor="middle">ClickHouse 等：历史</text>
<rect class="bx-heap" x="369.5" y="176" width="142.1" height="70" rx="8"/>
<text class="t-b" x="440.5" y="204" text-anchor="middle">推送网关</text>
<text class="t-s" x="440.5" y="226" text-anchor="middle">Netty + WebSocket</text>
<rect class="bx" x="189.5" y="176" width="142.1" height="70" rx="8"/>
<text class="t-b" x="260.5" y="204" text-anchor="middle">App / 网页</text>
<text class="t-s" x="260.5" y="226" text-anchor="middle">只收自己订阅的股票</text>
<rect class="bx" x="9.5" y="176" width="142.1" height="70" rx="8"/>
<text class="t-b" x="80.5" y="204" text-anchor="middle">查询接口</text>
<text class="t-s" x="80.5" y="226" text-anchor="middle">读 Redis / 历史库</text>
<path class="ln" d="M628.1 86L628.1 174" marker-end="url(#iq3-a)"/>
<text class="t-s" x="635.7" y="134">结果写入</text>
<path class="ln" d="M440.5 86L440.5 174" marker-end="url(#iq3-a)"/>
<text class="t-s" x="448.1" y="134">全量行情</text>
<path class="ln ln-pri" d="M367.6 211L333.5 211" marker-end="url(#iq3-p)"/>
<path class="ln ln-dash" d="M187.6 211L153.5 211" marker-end="url(#iq3-a)"/>
<text class="t-s" x="350.5" y="266" text-anchor="middle">合并后推送</text>
<text class="t-s" x="170.5" y="266" text-anchor="middle">进页面先拉一次</text>
</svg>
</div>
<figcaption>行情系统的大致链路。Kafka 按股票代码分区，保证同一只股票的行情按顺序处理；推送网关就是前面讲的 WebSocket 服务；用户进页面先用 HTTP 拉一次快照和 K 线，再接收推送。</figcaption>
</figure>

### 大数据组件，知道每个干什么

| 组件 | 一句话 | 证券场景 |
|---|---|---|
| Kafka | 高吞吐的消息队列：消息按分区顺序追加写磁盘，消费者自己记读到哪（offset），可以回头重新消费 | 行情分发、交易日志 |
| Flink | 流式计算：数据来一条算一条，支持按时间窗口聚合 | 实时生成 1 分钟 K 线、实时指标、异常交易监控 |
| Spark | 批量计算：一次处理一大批数据 | 收盘后的统计、策略回测 |
| Hive | 用 SQL 查存在 HDFS（分布式文件系统）上的大文件 | 离线数据仓库、报表 |
| HBase | 按行键（rowkey）快速读写的海量表 | 历史行情、逐笔明细 |
| ClickHouse | 列式数据库，大表统计聚合很快 | 行情历史分析、运营报表 |

### 常见问题

#### 1 分钟 K 线怎么生成？

按股票代码分组，每来一笔成交：这一分钟的第一笔价格是开盘价，最高、最低随时更新，最新一笔是收盘价，成交量累加。到这一分钟结束（按交易所给的时间戳，不按服务器收到的时间）就输出这根 K 线，开始下一根。

实现：Flink 按股票代码分组 + 1 分钟滚动窗口；自己写的话，内存里每只股票维护一根「正在生成的 K 线」，到点封口写库并推送。日 K、周 K 由分钟 K 再汇总，不要每次从逐笔数据现算。

**追问**：难点？→ 迟到的数据（窗口关闭后才到）；午间休市、集合竞价时段怎么算；某一分钟没有成交要不要补一根（用上一根的收盘价补）。

#### 行情分发为什么多用 Kafka，不用 RabbitMQ？

① 吞吐：Kafka 顺序写磁盘、批量发送，吞吐量比 RabbitMQ 高很多；② 顺序：同一分区内有序，按股票代码分区就能保证同一只股票按顺序处理；③ 可重放：消费后消息不删（按保留时间清理），新的计算任务可以从头再算一遍。RabbitMQ 的长处是路由灵活、单条消息确认可靠，适合订单、通知这类业务消息。

#### 行情推送和订单消息的处理有什么不同？

行情只要最新，可以合并、可以丢中间值，追求低延迟；订单、资金消息一条都不能丢、不能重复处理，要确认机制、要幂等、要能对账。所以两类消息走的通道和处理方式都应该分开设计。

#### 几十亿条历史行情怎么存？怎么查？

按日期分区、按股票代码排序存；用列式存储（只读需要的列、压缩率高）；当天数据和最新快照放 Redis 和内存，历史放时序库或 ClickHouse，更老的归档；K 线预先算好单独存，查询直接读结果。

## 十四、直播业务

直播系统里 Java 后端一般不处理音视频本身（交给云厂商），负责的是围绕直播的业务。

<figure class="fig">
<div class="fig-box">
<svg viewBox="0 0 720 296" role="img" aria-label="直播链路：主播推流、云直播分发、观众拉流；业务后端负责签名、回调、弹幕礼物">
<defs><marker id="iq4-a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah" d="M0 0L10 5L0 10z"/></marker><marker id="iq4-p" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah-pri" d="M0 0L10 5L0 10z"/></marker><marker id="iq4-s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah-sec" d="M0 0L10 5L0 10z"/></marker></defs>
<rect class="bx" x="18.9" y="30" width="142.1" height="64" rx="8"/>
<text class="t-b" x="90" y="57" text-anchor="middle">主播端</text>
<text class="t-s" x="90" y="78" text-anchor="middle">推流软件 / App</text>
<rect class="bx-heap" x="288.9" y="30" width="142.1" height="64" rx="8"/>
<text class="t-b" x="360" y="57" text-anchor="middle">云直播 + CDN</text>
<text class="t-s" x="360" y="78" text-anchor="middle">转码、分发到各地节点</text>
<rect class="bx" x="558.9" y="30" width="142.1" height="64" rx="8"/>
<text class="t-b" x="630" y="57" text-anchor="middle">观众端</text>
<text class="t-s" x="630" y="78" text-anchor="middle">播放器 + 长连接</text>
<path class="ln" d="M162.9 62L287.1 62" marker-end="url(#iq4-a)"/>
<text x="224.5" y="52" text-anchor="middle">RTMP 推流</text>
<path class="ln" d="M432.9 62L557.1 62" marker-end="url(#iq4-a)"/>
<text x="494.5" y="52" text-anchor="middle">拉流</text>
<text class="t-s" x="494.5" y="114" text-anchor="middle">FLV / HLS / WebRTC</text>
<rect class="bx-heap" x="217.9" y="200" width="284.2" height="80" rx="8"/>
<text class="t-b" x="360" y="228" text-anchor="middle">业务后端（Java）</text>
<text class="t-s" x="360" y="250" text-anchor="middle">直播间、推流签名、回调、弹幕</text>
<text class="t-s" x="360" y="268" text-anchor="middle">礼物、在线人数、排行榜</text>
<path class="ln ln-dash" d="M248.2 198L104.2 96" marker-end="url(#iq4-a)"/>
<text x="11.4" y="150">① 下发带签名的推流地址</text>
<path class="ln" d="M360 96L360 198" marker-end="url(#iq4-a)"/>
<text x="369.5" y="150">② 开播 / 断流 / 录制回调</text>
<path class="ln ln-pri" d="M630 96L475.6 198" marker-end="url(#iq4-p)"/>
<text class="t-pri" x="710.5" y="150" text-anchor="end">③ 弹幕、点赞、礼物</text>
<text class="t-s" x="710.5" y="169" text-anchor="end">WebSocket 长连接</text>
</svg>
</div>
<figcaption>音视频走上面一行，由云厂商处理；后端做下面这块：给主播生成推流地址、接收云厂商的回调、通过长连接处理弹幕点赞礼物。</figcaption>
</figure>

### 音视频怎么走（知道名字和区别就够）

- **推流**：主播端把音视频用 RTMP 协议推到云直播服务器。
- **转码、分发**：云厂商把一路视频转成不同清晰度，通过 CDN（分布在各地的缓存节点）分发，观众就近拉取。
- **拉流**：HTTP-FLV 延迟较低；HLS 把视频切成一小段一小段的文件，兼容性最好但延迟更高；WebRTC 延迟最低，常用于连麦互动。具体延迟和配置有关。
- **推流地址加签名**：地址里带过期时间和用密钥算出的签名，云端校验，防止别人拿到地址盗推。
- **回调**：开始推流、断流、录制完成时，云厂商回调你的接口——要校验签名、要幂等，和对接支付回调是一回事。

### 后端要做的业务和难点

| 功能 | 难点 | 怎么做 |
|---|---|---|
| 弹幕 | 大直播间几万人，每条弹幕要推给所有人 | WebSocket 长连接，按直播间分组；每 200–500 毫秒把这段时间的弹幕打包推一次；人多时普通弹幕抽样推，礼物和系统消息优先；敏感词过滤 |
| 在线人数 | 要实时、要去重 | 心跳维持在线；每台推送机器统计本机各房间的连接数，定时汇总到 Redis；要去重统计看过的人数用 Redis HyperLogLog（每个 key 约 12KB，误差约 0.81%） |
| 点赞 | 一秒几万次 | 客户端攒一批再发；服务端本机先累加，每秒批量 `INCRBY` 到 Redis，再定时写库 |
| 礼物打赏 | 扣钱不能多扣、少扣、重复扣 | 带条件扣减 + 流水 + 幂等 + 对账，见场景题 3 |
| 排行榜 | 实时更新贡献榜 | Redis 有序集合 `ZINCRBY` 加分，`ZREVRANGE` 取前几名 |
| 回放、审核 | 合规（证券类直播尤其严） | 云端录制回调里拿到文件地址存起来；内容审核接云厂商的审核服务 |

### 常见问题

#### 直播间在线人数怎么统计？

当前在线：每个连接靠心跳维持，每台推送机器知道本机每个房间有多少连接，定时（比如每 5 秒）写到 Redis Hash（房间 → 各机器人数），读的时候求和。累计观看人数（要去重）：每个进房间的 userId 加进 Redis HyperLogLog，`PFCOUNT` 取估算值，12KB 能估算海量用户，误差约 0.81%；要精确就用 Set，但大房间很占内存。

#### 点赞量特别大怎么办？

不要每次点赞都写数据库：客户端 1 秒内的多次点赞合并成一次请求发上来；服务端在内存里按房间累加，每秒一次 `INCRBY` 到 Redis；Redis 的数再定时写回数据库。代价是点赞数有一两秒延迟，业务上可以接受。

#### 推流地址为什么要签名？

防止别人拿到推流地址往你的直播间推内容（盗推）。地址里带过期时间戳和「密钥 + 流名 + 过期时间」算出的签名，云端用同样的密钥校验，过期或签名不对就拒绝推流。

#### 后端视角，直播业务的核心是什么？

拆成三块：长连接推送（WebSocket 那一套）；高并发写（点赞、弹幕的合并写）；资金一致性（礼物打赏：带条件扣减、流水、幂等、对账）。

## 十五、场景设计题

答题顺序：**先问清楚规模和要求（1 分钟）→ 画分层结构 → 讲 2–3 个难点和取舍 → 说怎么监控、怎么扩容**。不要一上来就报一串技术名词。

### 题 1 设计实时行情推送

**题目**：App 同时 10 万人在线，每人自选几十只股票，行情每秒都在变，要实时推到 App。

**先问**：峰值在线多少？延迟要求多少（1 秒内？）？只推自选股，还是还有指数、排行榜？

**参考答案**

1. **接入**：行情接收服务从行情源拿数据，解码、校验，按股票代码分区写入 Kafka（见行情链路图）。
2. **推送层**：多台 Netty WebSocket 推送机器，每台都消费全量行情；每台在内存里维护「股票代码 → 订阅了它的连接集合」。
3. **订阅**：客户端连上后发「订阅 600519」，服务端把连接加进对应集合；改自选就增减订阅；连接断开时从所有集合里移除。
4. **合并推送**：同一只股票 200 毫秒内的多次变化只推最后一次；同一个连接订阅的多只股票合成一个包推，减少消息条数。
5. **进页面**：先用 HTTP 从 Redis 拉一次最新快照，再接收增量推送，避免页面先空着。
6. **扩容**：推送机器上的订阅关系是连接建立后才有的，机器挂了客户端重连到别的机器重新订阅就行，所以加机器就能扩；前面用四层负载均衡分配连接。

**追问**：某只股票特别热？→ 同一份数据只序列化一次，再写给所有订阅的连接，不要每个连接序列化一次。慢客户端？→ `isWritable()` 为 false 时只保留最新一条。怎么监控？→ 连接数、推送延迟（行情时间戳到推出去的时间差）、Kafka 消费积压量。

### 题 2 设计直播间弹幕和在线人数

**先问**：最大的直播间多少人？弹幕要不要保存、要不要审核？

**参考答案**

1. **发弹幕**：走 HTTP 接口（或 WebSocket 上行）→ 校验登录、限频（每人每秒 1 条）、敏感词过滤 → 写 MQ。
2. **分发**：MQ 广播给所有推送机器（fanout），每台推给本机在这个房间的连接；连接按房间分组存在本机内存（见多机推送图）。
3. **大房间**：每 200–500 毫秒打包推一次；人多时普通弹幕抽样，礼物、主播消息、系统公告不抽样；特别大的房间单独部署推送机器。
4. **存储**：弹幕异步写 MongoDB 或 ES（回放、审核、搜索），不在发送主流程里同步写。
5. **在线人数**：见直播业务一节。

**追问**：弹幕要不要严格有序？→ 同一个人的弹幕按时间排即可，全房间严格有序代价大、意义小。推送机器挂了？→ 客户端重连到别的机器，重新进房间。

### 题 3 直播礼物打赏，怎么保证扣钱正确

**题目**：用户送一个 100 元的礼物，要扣用户余额、给主播加收益、直播间播特效、更新贡献榜。

**参考答案**

1. **防重复**：客户端每次送礼生成唯一请求号，服务端礼物订单表对它建唯一索引，重复请求直接返回第一次的结果。
2. **扣余额**：一个本地事务里做三件事——带条件扣减 `UPDATE account SET balance = balance - 100 WHERE user_id = ? AND balance >= 100`（影响 0 行就是余额不足；不要先查再改，并发时会超扣）；写礼物订单；写资金流水。
3. **主播收益**：在另一个库或服务时，不放进同一个大事务。用本地消息表：扣款事务里同时写一条「给主播加钱」的待发消息，定时任务投递直到成功，主播侧按订单号幂等入账。
4. **特效和榜单**：扣款成功后发 MQ，推送服务广播特效，Redis 有序集合更新榜单；这些失败了不影响钱，可以重试或放弃。
5. **对账**：每天按订单核对：用户扣款总额 = 主播入账总额 + 平台分成。

**追问**：热门主播的收益账户一秒被加几千次，行锁冲突严重？→ 主播侧先只记流水，异步汇总到余额；或者把一个账户拆成多个子账户分散写，查询时求和。为什么不用 Seata 这类分布式事务框架？→ 链路短，本地消息表 + 幂等足够，也更好排查。

### 题 4（备选）热门股票详情页，读请求特别多

思路见[《热点商品缓存击穿》](/blog/scenario-cache-breakdown/)和[《Redis 面试笔记》](/blog/redis-interview-notes/)里的缓存一致性、穿透击穿雪崩。补一句：行情这种「每秒都变」的数据不适合「先改库再删缓存」的套路，应该由行情服务直接写 Redis 最新快照，页面只读 Redis。
