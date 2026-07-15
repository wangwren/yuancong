---
title: 短信平台频繁 Full GC 问题排查与优化
description: 每分钟 15-16 次 Full GC：从 GC 日志分析到启动参数调整的完整排查过程。
pubDate: 2026-04-21
tags: [场景题]
---
## 一、问题现象

- 服务：`lark-smsx [8080]`，短信项目
- 告警：`full gc count > 5/min`
- 监控图表显示Full GC频繁，峰值达40次，长期在告警阈值附近徘徊
- 之前通过修改JVM参数（CMS换G1）临时缓解，但未根治

---

## 二、排查过程

### 第一步：确认GC日志位置和版本

```bash
# 确认日志是否最新
tail -20 gc.log
```

发现日志头部CommandLine flags显示使用的是 **CMS GC**（`-XX:+UseConcMarkSweepGC`），而不是之前以为的G1，原来两台机器只有一台改了参数。

> **教训：排查前先确认当前环境的实际配置，不要想当然。**

---

### 第二步：找到Full GC发生时间段的日志

```bash
grep "2026-04-15T08:3[0-9]" gc.log | head -30
```

发现报警时间段内Old区数据：

```
CMS-remark: 1292342K(1835008K)  ← 回收前
CMS-remark: 1292342K(1835008K)  ← 回收后几乎没变化
```

> **关键发现：CMS每轮跑完，Old区只回收了几KB，基本等于没回收。**

---

### 第三步：定位Full GC触发瞬间

通过 `grep -i "full"` 找到full计数器，再用行号定位：

```bash
grep -n "full 9967\|full 9968\|full 9969\|full 9970" gc.log | head -20
sed -n '1811981,1812030p' gc.log
```

观察到Old区变化：

```
1294668K → sweep → 1294656K → sweep → 1294654K → sweep → 1294650K
```

> **每次CMS完整回收一轮，Old区只减少几KB，对象几乎全部存活，Old区迟早撑爆触发Full GC。**

---

### 第四步：用jmap找异常对象

```bash
jmap -histo $(pgrep -f lark-smsx) | head -30
```

输出关键数据：

```
1: 7946763   764919576  [C
2: 7466588   298663520  java.util.LinkedHashMap$Entry
3: 7693042   184633008  java.lang.String
```

> **发现：746万个LinkedHashMap$Entry占285MB，异常明显。**

---

### 第五步：排除误判，验证数据量

初步怀疑是 `QuotaFilter` 每次请求都调用 `hgetAll` 产生大量LinkedHashMap，但验证后发现：

```bash
redis-cli hlen quota   # 返回 6
```

Redis里quota只有6条数据，和jmap里257个Entry/Map对不上，说明LinkedHashMap来源另有其他地方，初步分析方向有偏差。

> **教训：分析结论要用数据验证，不能只看代码推断。**

---

### 第六步：jmap -dump + MAT深度分析

`-histo` 只能看到有什么对象，看不出谁持有这些对象，需要dump文件分析引用链：

```bash
# 确认磁盘空间（dump文件约等于堆实际使用量，这里约1.5G）
df -h /tmp

# 生成堆快照
jmap -dump:format=b,file=/tmp/heap.hprof $(pgrep -f lark-smsx)
```

下载到本地用 **MAT（Eclipse Memory Analyzer）** 打开，Leak Suspects报告显示：

```
java.io.DeleteOnExitHook 占堆内存94%
内部LinkedHashMap有600万+条 /tmp/jar_cacheXXXX.tmp 路径
```

MAT分析过程，使用柱状图其实就能发现这个DeleteOnExitHook的问题，浅堆为0，深堆很大。
![](https://img.yuancong.ai/blog/scenario-full-gc-tuning/01.jpg)

用支配树能发现这里的jar_cachexxx是有问题的，但是还是没找到代码中在哪使用
![](https://img.yuancong.ai/blog/scenario-full-gc-tuning/02.jpg)
Leak Suspects（可疑泄漏对象） 是 MAT 自动分析后给出的：最可能导致内存占用异常 / 内存泄漏的对象集合

![](https://img.yuancong.ai/blog/scenario-full-gc-tuning/03.jpg)
其实在这MAT就已经发现问题了，后续我在代码中搜索`deleteOnExit()`，搜不到，就有了接下来的步骤。


---

### 第七步：Arthas追踪调用栈

项目代码里搜不到 `deleteOnExit()`，说明是框架内部调用，用Arthas动态追踪：

```bash
# 挂载到目标进程
java -jar arthas-boot.jar <pid>

# 开启 unsafe 模式（允许增强 JDK 类）
options unsafe true

# 追踪调用栈
stack java.io.File deleteOnExit -n 5
```

调用栈：

```
java.io.File.deleteOnExit()
  ← sun.net.www.protocol.jar.URLJarFile.retrieve()         # JDK 创建 jar_cache 临时文件
    ← JarURLConnection.getContentLength()                   # 获取 JAR 内资源大小
      ← AbstractFileResolvingResource.contentLength()       # Spring 读取资源的 Content-Length
        ← ResourceHttpRequestHandler.setHeaders()           # 设置 HTTP 响应头
          ← ResourceHttpRequestHandler.handleRequest()      # 服务静态资源
            ← InternalResourceView.renderMergedOutputModel() # Controller 视图转发
              ← HttpServlet.doHead()                        # 收到 HTTP HEAD 请求
```

>ResourceHttpRequestHandler 服务静态文件 + InternalResourceView 做转发，这个组合在 Spring Boot 里几乎只有 Swagger UI 会触发
查看 celebi-server-1.8.7.jar 内部，发现 SwaggerConfiguration.class，确认 celebi 框架自动开启了 Swagger
常量池中发现配置开关 celebi.server.swagger.enabled，且 matchIfMissing=true（不配置就默认启用） **指向Swagger UI的静态资源请求。**

---

## 三、根本原因

两个因素叠加导致问题：

| 因素                      | 说明                                                         |
| ------------------------- | ------------------------------------------------------------ |
| Spring Boot 1.5.x缺陷     | `ResourceHttpRequestHandler` 每次请求都通过 `JarURLConnection` 读取嵌套JAR内文件大小，不缓存，每次都创建临时文件并调用 `deleteOnExit()` |
| Celebi框架默认开启Swagger | 生产环境不需要Swagger，但 `celebi.server.swagger.enabled` 默认为true，Swagger UI静态资源暴露在外 |

**完整触发链路：**

```
监控/网关每秒发送 HEAD /swagger-ui.html
  → Spring ResourceHttpRequestHandler 服务 webjar 内静态文件
  → 每次请求打开 JarURLConnection（无缓存）
  → URLJarFile.retrieve() 创建临时文件
  → File.deleteOnExit() 写入 DeleteOnExitHook.files
  → LinkedHashSet永不清除，持续累积
  → 运行数天后累积600万条 → 285MB堆内存 → Full GC
```

---

## 四、解决方案

在生产环境配置中加入：

```properties
# 关闭Swagger（治本）
celebi.server.swagger.enabled=false

# 开启静态资源缓存（兜底）
spring.resources.chain.enabled=true
spring.resources.chain.cache=true
spring.resources.cache.period=86400
```

重启后 `DeleteOnExitHook` 不再增长，Full GC消失。

---

## 五、工具总结

| 工具        | 用途                                   | 本次使用场景                       |
| ----------- | -------------------------------------- | ---------------------------------- |
| gc.log      | 查看GC历史记录、触发原因、各区内存变化 | 确认Full GC存在，发现Old区无法回收 |
| jmap -histo | 快速列出堆内所有类的实例数和内存占用   | 发现LinkedHashMap异常堆积          |
| jmap -dump  | 导出完整堆快照供MAT分析                | 找到DeleteOnExitHook占94%堆内存    |
| MAT         | 分析堆快照，找内存泄漏和引用链         | 定位到具体持有者和路径             |
| Arthas      | 动态追踪方法调用栈，不需要重启         | 找到deleteOnExit()的调用来源       |

**排查优先级：gc.log → jmap -histo → jmap -dump + MAT → Arthas**，从轻到重，够用就不用下一级。

---

## 六、额外收获

**CMS换G1治标不治本**：另一台换成G1的机器根因相同，早晚也会Full GC，需要同步修复。

**jmap -histo的局限性**：只能看到对象数量和大小，看不出引用关系。当 `-histo` 结果无法直接定位问题时，必须上MAT分析引用链。

**CMS GC和Full GC的区别**：

- **CMS GC**：并发回收，和应用线程同时运行，不会停顿，频繁触发没关系
- **Full GC**：STW（Stop The World），应用完全停止，这才是报警的原因
- `CMSInitiatingOccupancyFraction=70` 触发的是CMS GC，不是Full GC