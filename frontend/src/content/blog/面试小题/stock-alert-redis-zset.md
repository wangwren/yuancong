---
title: Redis 有序集合的原理和 8 个用法
description: 交易所每 3 秒推 6000 只股票行情，用户设了 200 万条预警，行情一来怎么马上找到该提醒的人；有序集合是什么、怎么用、底层怎么实现，以及排行榜、订单超时取消、限流、附近门店等 8 个用法。
pubDate: 2026-11-25
tags: [Redis, 场景题]
---

这道题考的是：从一大堆条件里，怎么快速找出刚被满足的那几个。想通了它，排行榜、订单超时取消、限流这些题用的也是同一个思路。

## 一、题目

交易所每 3 秒推一次全部股票的最新价格，一共 6000 只。用户可以给自选股设预警，比如「涨到 10.50 元提醒我」「跌到 9 元提醒我」「涨幅超过 5% 提醒我」，所有用户加起来一共 200 万条。股价一到，怎么快速找到要提醒的用户？

## 二、容易卡住的思路

最先想到的通常是：把预警按股票代码分组存进 Redis，比如用 Hash，键是股票代码；行情来了，按股票代码找到这只股票的所有预警，一条条算涨跌幅、比大小。

这样会卡在两个地方：

1. **只能一条条比**。热门股可能有十几万人设了预警，每 3 秒都要全部拿出来比一遍。Hash 里的字段没有顺序，Redis 回答不了「提醒价在 10.15 到 10.30 之间的有谁」，只能把整组都拿出来。
2. **会重复提醒**。只比「现价 ≥ 提醒价」，股价站上 10.50 以后，每 3 秒都满足一次，用户每 3 秒收到一条提醒。

## 三、换个方向：先把人按提醒价排好队，再拿价格去查

不要拿每个人的条件去和价格比，而是反过来：**先把所有人按提醒价排好队，行情来了，拿现价去队伍里查。** 就像查字典，单词按字母排好了，找一个词不用从第一页翻起。

### 1. 先把所有条件换算成提醒价

| 用户设的条件 | 怎么换算 | 结果 |
|---|---|---|
| 涨到 X 元 | 不用换 | 涨到 X |
| 跌到 X 元 | 不用换 | 跌到 X |
| 涨幅达到 5% | 昨收一整天不变，开盘前算一次：昨收 × 1.05 | 涨到某个价 |
| 跌幅达到 5% | 昨收 × 0.95 | 跌到某个价 |

这样，所有预警都变成了两种：「涨到某个价」和「跌到某个价」。

### 2. 每只股票两张排好序的名单

每只股票准备两张名单，一张记「涨到」，一张记「跌到」。名单里按提醒价从低到高排好，不管谁先设、谁后设。

<figure class="fig">
<div class="fig-box">
<svg viewBox="0 0 720 304" role="img" aria-label="股票 X 的涨到名单和跌到名单，现价 10.30 时取出张三和李四">
<text class="t-b" x="20" y="24">股票 X · 涨到名单（按提醒价从低到高）</text>
<rect class="bx-heap" x="20" y="38" width="104" height="56" rx="8"/>
<text x="72" y="62" text-anchor="middle">10.20</text>
<text class="t-s" x="72" y="82" text-anchor="middle">张三</text>
<rect class="bx-heap" x="132" y="38" width="104" height="56" rx="8"/>
<text x="184" y="62" text-anchor="middle">10.20</text>
<text class="t-s" x="184" y="82" text-anchor="middle">李四</text>
<rect class="bx" x="244" y="38" width="104" height="56" rx="8"/>
<text x="296" y="62" text-anchor="middle">10.50</text>
<text class="t-s" x="296" y="82" text-anchor="middle">王五</text>
<rect class="bx" x="356" y="38" width="104" height="56" rx="8"/>
<text x="408" y="62" text-anchor="middle">10.80</text>
<text class="t-s" x="408" y="82" text-anchor="middle">小周</text>
<rect class="bx" x="468" y="38" width="104" height="56" rx="8"/>
<text x="520" y="62" text-anchor="middle">11.00</text>
<text class="t-s" x="520" y="82" text-anchor="middle">小吴</text>
<rect class="bx" x="580" y="38" width="104" height="56" rx="8"/>
<text x="632" y="62" text-anchor="middle">11.20</text>
<text class="t-s" x="632" y="82" text-anchor="middle">小郑</text>
<path class="ln ln-pri" d="M20 102V110H236V102"/>
<text class="t-pri" x="20" y="134">现价 10.30：从最前面往后取，取出张三、李四，同时从名单删掉</text>
<text class="t-s" x="20" y="156">取到王五时，10.50 已经超过现价，就停下，后面的一个都不用看</text>
<text class="t-b" x="20" y="200">股票 X · 跌到名单（按提醒价从低到高）</text>
<rect class="bx" x="20" y="214" width="104" height="56" rx="8"/>
<text x="72" y="238" text-anchor="middle">9.00</text>
<text class="t-s" x="72" y="258" text-anchor="middle">小林</text>
<rect class="bx" x="132" y="214" width="104" height="56" rx="8"/>
<text x="184" y="238" text-anchor="middle">9.20</text>
<text class="t-s" x="184" y="258" text-anchor="middle">小孙</text>
<rect class="bx" x="244" y="214" width="104" height="56" rx="8"/>
<text x="296" y="238" text-anchor="middle">9.50</text>
<text class="t-s" x="296" y="258" text-anchor="middle">赵六</text>
<rect class="bx" x="356" y="214" width="104" height="56" rx="8"/>
<text x="408" y="238" text-anchor="middle">9.70</text>
<text class="t-s" x="408" y="258" text-anchor="middle">小钱</text>
<rect class="bx" x="468" y="214" width="104" height="56" rx="8"/>
<text x="520" y="238" text-anchor="middle">9.80</text>
<text class="t-s" x="520" y="258" text-anchor="middle">小冯</text>
<rect class="bx" x="580" y="214" width="104" height="56" rx="8"/>
<text x="632" y="238" text-anchor="middle">9.90</text>
<text class="t-s" x="632" y="258" text-anchor="middle">小陈</text>
<text class="t-s" x="20" y="294">跌下来时反过来：在跌到名单里取提醒价 ≥ 现价的，从最后面往前取</text>
</svg>
</div>
<figcaption>图 1　每只股票两张名单，各自按提醒价排好序</figcaption>
</figure>

### 3. 行情来了怎么查

用一个小例子走一遍。涨到名单里有张三 10.20、李四 10.20、王五 10.50，跌到名单里有赵六 9.50：

| 现价 | 问哪张名单 | 问什么 | 得到 | 接着做什么 |
|---|---|---|---|---|
| 10.15 | 涨到 | 提醒价 ≤ 10.15 的有谁 | 没人 | 不用做 |
| 10.30 | 涨到 | 提醒价 ≤ 10.30 的有谁 | 张三、李四 | 提醒他俩，再从名单删掉 |
| 10.40 | 涨到 | 提醒价 ≤ 10.40 的有谁 | 没人（张三、李四已经删了） | 不用做 |
| 9.40 | 跌到 | 提醒价 ≥ 9.40 的有谁 | 赵六 | 提醒他，再删掉 |

三个要点：

- **为什么快**：名单一直是排好序的。问「≤ 10.30 的有谁」，从最前面往后取，碰到第一个超过 10.30 的就停，后面的人一个都不用看。
- **取出来就删掉**：顺手解决了重复提醒，当天不会再提醒同一个人。
- **涨、跌要分开排**：如果放在一张名单里，现价 10.60 时问「≤ 10.60 的有谁」，会把设了「跌到 9.50」的人也查出来。

## 四、Redis 有序集合

上面说的「排好序的名单」，Redis 里有现成的：**有序集合**（Sorted Set，命令都以 Z 开头，所以也常叫 ZSet）。

### 1. Redis 常用的五种类型

| 类型 | 相当于 Java 里的 | 这道题能不能用 |
|---|---|---|
| String | 一个键对应一个值 | 不行：一个键只能放一个值 |
| Hash | `Map<键, Map<字段, 值>>` | 不行：字段没有顺序 |
| List | `LinkedList` | 不行：按放进去的先后排，不按价格排 |
| Set | `HashSet` | 不行：没有顺序 |
| **Sorted Set 有序集合** | 有点像 `TreeMap`，按「分数」排序 | **可以**：按分数自动排序，能按分数范围取 |

### 2. 有序集合是一张自动排好序的名单

- 名单的名字就是**键**。
- 名单里每一行就两样东西：**成员**（一个字符串）和**分数**（一个数字）。
- 不管按什么顺序加进去，名单永远按分数从小到大排好。分数相同的，按成员字符串的字节顺序排。
- 能直接问「分数在多少到多少之间的有谁」，也能问「排第几到第几的是谁」。

两条规则要记住：

- **分数只能是数字**。写成「十块五」或「10.5元」，Redis 都会报错 `ERR value is not a valid float`（不是合法的数字）。要记的文字信息都放进成员里。
- **同一张名单里，成员不能重复**。对已经在名单里的成员再加一次，不会多出一行，只会把它的分数改掉。

### 3. 用到的命令

下面命令的返回结果只列内容，省掉了 redis-cli 显示的编号和引号。先把英文拆开：Z 开头的命令都是操作有序集合的；ADD 是「加」，RANGE 是「范围」，BY SCORE 是「按分数」，REM 是「删除」（remove 的缩写）。`-inf` 是负无穷，意思是没有下限；`+inf` 是正无穷，没有上限。

```text
# 往名单里加人：先写分数，再写成员，一次可以加多个
> ZADD 股票X-涨到 10.20 张三 10.20 李四 10.50 王五
3

# 现价 10.15：提醒价 ≤ 10.15 的有谁
> ZRANGEBYSCORE 股票X-涨到 -inf 10.15
（空）

# 现价 10.30：提醒价 ≤ 10.30 的有谁
> ZRANGEBYSCORE 股票X-涨到 -inf 10.30
张三
李四

# 把这些人从名单删掉，返回删了几个
> ZREMRANGEBYSCORE 股票X-涨到 -inf 10.30
2

# 跌到名单：现价 9.40，提醒价 ≥ 9.40 的有谁
> ZADD 股票X-跌到 9.50 赵六
1
> ZRANGEBYSCORE 股票X-跌到 9.40 +inf
赵六
```

### 4. 真正上线时的写法

上面为了好懂用了中文名字和元，上线时要改两处：

1. **提醒价存成「分」，用整数**。10.20 存进去，Redis 里实际存的是 10.199999999999999，因为小数在电脑里存不精确，比大小时可能差一点点。存成 1020（分）就没有这个问题。
2. **成员写成「预警编号 + 用户编号」，不能只写人名**。同一个人在同一只股票上设了两个提醒价，只写人名的话，第二个会覆盖第一个。推送时需要的其他信息（推到哪、提醒文案），拿预警编号去数据库查完整记录。

键、分数、成员都是代码按规则拼出来的：

| 部分 | 例子 | 怎么拼 |
|---|---|---|
| 键（名单的名字） | `alert:rise:X` | `"alert:"` + 方向（涨到写 `rise`，跌到写 `fall`）+ `":"` + 股票代码 |
| 分数 | `1050` | 提醒价换算成分 |
| 成员 | `a1:u1001` | `"a"` + 预警编号 + `":u"` + 用户编号 |

查的时候也是两步：行情里带着股票代码，代码按同样的规则拼出键，找到这张名单；再在名单里按分数取范围。

### 5. 取出和删除要放进一个 Lua 脚本

「取出」和「删除」如果分成两条命令发，中间可能插进别的操作：

- 另一台机器也取了一次，同一个用户被提醒两次；
- 现价 10.30 时，用户正好在「取」之后、「删」之前新加了一条「涨到 10.25」，这条没被取到就被删了，永远不会提醒。

Redis 支持把几条命令写成一段 Lua 小程序，一次发过去执行，执行期间不会插进别的命令，两步就像一步：

```lua
-- KEYS[1] = 名单的键；ARGV[1]、ARGV[2] = 分数范围
local hit = redis.call('ZRANGEBYSCORE', KEYS[1], ARGV[1], ARGV[2])
if #hit > 0 then
    redis.call('ZREMRANGEBYSCORE', KEYS[1], ARGV[1], ARGV[2])
end
return hit
```

### 6. Java 代码（Spring Data Redis）

```java
@Component
public class AlertMatcher {

    /** 按分数范围取出成员并删掉，两步在 Redis 里一次执行完 */
    @SuppressWarnings("rawtypes")
    private static final DefaultRedisScript<List> MATCH_SCRIPT = new DefaultRedisScript<>(
            "local hit = redis.call('ZRANGEBYSCORE', KEYS[1], ARGV[1], ARGV[2]) "
                    + "if #hit > 0 then redis.call('ZREMRANGEBYSCORE', KEYS[1], ARGV[1], ARGV[2]) end "
                    + "return hit",
            List.class);

    private final StringRedisTemplate redis;

    public AlertMatcher(StringRedisTemplate redis) {
        this.redis = redis;
    }

    /** 用户新增预警；同一条预警再调一次就是修改提醒价 */
    public void save(String code, boolean rise, long alertId, long userId, long priceFen) {
        redis.opsForZSet().add(key(code, rise), member(alertId, userId), priceFen);
    }

    /** 用户删除预警 */
    public void delete(String code, boolean rise, long alertId, long userId) {
        redis.opsForZSet().remove(key(code, rise), member(alertId, userId));
    }

    /** 行情到达：返回要提醒的成员，格式「a预警编号:u用户编号」 */
    @SuppressWarnings("unchecked")
    public List<String> onTick(String code, long priceFen) {
        String p = String.valueOf(priceFen);
        List<String> hit = new ArrayList<>();
        hit.addAll(redis.execute(MATCH_SCRIPT, List.of(key(code, true)), "-inf", p));
        hit.addAll(redis.execute(MATCH_SCRIPT, List.of(key(code, false)), p, "+inf"));
        return hit;
    }

    private static String key(String code, boolean rise) {
        return "alert:" + (rise ? "rise:" : "fall:") + code;
    }

    private static String member(long alertId, long userId) {
        return "a" + alertId + ":u" + userId;
    }
}
```

两个要注意的地方：

- **要用 `StringRedisTemplate`**。Spring Boot 默认的 `RedisTemplate` 用 Java 自带的序列化，成员和参数会变成一串二进制，脚本收到的 `-inf` 不再是 `-inf`，Redis 会报「不是数字」的错。
- **一轮行情要批量发**。6000 只股票、每只查两张名单，一共 12000 次调用。一条一条发，每次都要等一个网络来回；用管道（pipeline，把一批命令一次发出去，再一次把回复都收回来），Spring 里对应 `executePipelined`。价格没变的股票可以不查。

### 7. 量有多大

- 200 万条预警全放进 Redis，大约两百 MB 内存，平均每条一百来字节（和成员字符串长短、内存分配方式有关）。
- 一轮行情的 12000 次脚本调用用管道一次发出，几十毫秒就能做完，离 3 秒还远。
- 一张十几万人的热门股名单，查一次只要几十微秒。

## 五、有序集合底层怎么实现

面试常接着问底层，分两种情况：

- **元素少的时候**，用 listpack 存：一块连续的内存，元素按分数挨着放，省内存。Redis 7.0 的默认配置是：不超过 128 个元素、每个成员不超过 64 字节（配置项 `zset-max-listpack-entries`、`zset-max-listpack-value`）。
- **超过以后**，换成**跳表 + 哈希表**两个结构一起用：
  - **跳表**：先有一条按分数排好序的链表，再在上面加几层「快速通道」，越往上一层，跳过的节点越多。查找从最上层开始往前跳，下一个比目标大就往下一层，像坐地铁先坐快线、再换慢线。
  - **哈希表**：存「成员 → 分数」，用来一步查到某个成员在不在、分数是多少，比如 `ZSCORE`，还有 `ZADD` 时判断成员是不是已经在名单里。

<figure class="fig">
<div class="fig-box">
<svg viewBox="0 0 720 248" role="img" aria-label="跳表找 9.70：在上层往前跳，下一个比目标大就往下一层">
<defs><marker id="sz2-a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah" d="M0 0L10 5L0 10z"/></marker><marker id="sz2-p" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah-pri" d="M0 0L10 5L0 10z"/></marker></defs>
<text class="t-s" x="180" y="20">下一个是 9.80，比 9.70 大 → 往下一层</text>
<rect class="bx-dim" x="20" y="28" width="64" height="36" rx="6"/>
<text class="t-s" x="52" y="51" text-anchor="middle">第 3 层</text>
<rect class="bx" x="100" y="28" width="64" height="36" rx="6"/>
<text x="132" y="51" text-anchor="middle">9.00</text>
<rect class="bx" x="404" y="28" width="64" height="36" rx="6"/>
<text x="436" y="51" text-anchor="middle">9.80</text>
<path class="ln ln-pri" d="M84 46H98" marker-end="url(#sz2-p)"/>
<path class="ln" d="M164 46H402" marker-end="url(#sz2-a)"/>
<path class="ln ln-pri" d="M132 64V86" marker-end="url(#sz2-p)"/>
<text class="t-s" x="330" y="80">9.80 还是大 → 往下</text>
<rect class="bx-dim" x="20" y="88" width="64" height="36" rx="6"/>
<text class="t-s" x="52" y="111" text-anchor="middle">第 2 层</text>
<rect class="bx" x="100" y="88" width="64" height="36" rx="6"/>
<text x="132" y="111" text-anchor="middle">9.00</text>
<rect class="bx" x="252" y="88" width="64" height="36" rx="6"/>
<text x="284" y="111" text-anchor="middle">9.50</text>
<rect class="bx" x="404" y="88" width="64" height="36" rx="6"/>
<text x="436" y="111" text-anchor="middle">9.80</text>
<rect class="bx" x="556" y="88" width="64" height="36" rx="6"/>
<text x="588" y="111" text-anchor="middle">10.20</text>
<path class="ln" d="M84 106H98" marker-end="url(#sz2-a)"/>
<path class="ln ln-pri" d="M164 106H250" marker-end="url(#sz2-p)"/>
<path class="ln" d="M316 106H402" marker-end="url(#sz2-a)"/>
<path class="ln" d="M468 106H554" marker-end="url(#sz2-a)"/>
<path class="ln ln-pri" d="M284 124V146" marker-end="url(#sz2-p)"/>
<rect class="bx-dim" x="20" y="148" width="64" height="36" rx="6"/>
<text class="t-s" x="52" y="171" text-anchor="middle">第 1 层</text>
<rect class="bx" x="100" y="148" width="64" height="36" rx="6"/>
<text x="132" y="171" text-anchor="middle">9.00</text>
<rect class="bx" x="176" y="148" width="64" height="36" rx="6"/>
<text x="208" y="171" text-anchor="middle">9.20</text>
<rect class="bx" x="252" y="148" width="64" height="36" rx="6"/>
<text x="284" y="171" text-anchor="middle">9.50</text>
<rect class="bx-heap" x="328" y="148" width="64" height="36" rx="6"/>
<text class="t-b" x="360" y="171" text-anchor="middle">9.70</text>
<rect class="bx" x="404" y="148" width="64" height="36" rx="6"/>
<text x="436" y="171" text-anchor="middle">9.80</text>
<rect class="bx" x="480" y="148" width="64" height="36" rx="6"/>
<text x="512" y="171" text-anchor="middle">9.90</text>
<rect class="bx" x="556" y="148" width="64" height="36" rx="6"/>
<text x="588" y="171" text-anchor="middle">10.20</text>
<rect class="bx" x="632" y="148" width="64" height="36" rx="6"/>
<text x="664" y="171" text-anchor="middle">10.50</text>
<path class="ln" d="M84 166H98" marker-end="url(#sz2-a)"/>
<path class="ln" d="M164 166H174" marker-end="url(#sz2-a)"/>
<path class="ln" d="M240 166H250" marker-end="url(#sz2-a)"/>
<path class="ln ln-pri" d="M316 166H326" marker-end="url(#sz2-p)"/>
<path class="ln" d="M392 166H402" marker-end="url(#sz2-a)"/>
<path class="ln" d="M468 166H478" marker-end="url(#sz2-a)"/>
<path class="ln" d="M544 166H554" marker-end="url(#sz2-a)"/>
<path class="ln" d="M620 166H630" marker-end="url(#sz2-a)"/>
<text class="t-s" x="20" y="214">找 9.70：往前跳 3 次、往下走 2 次就到了（彩色的线），第 1 层的 9.20 根本没经过</text>
<text class="t-s" x="20" y="236">每往上一层，节点都少很多，所以 N 个元素找一个位置的步数大约和 log N 成正比</text>
</svg>
</div>
<figcaption>图 2　跳表：在上层往前跳，下一个比目标大就往下一层</figcaption>
</figure>

`ZRANGEBYSCORE` 的时间复杂度，官方文档写的是 O(log(N)+M)：N 是名单里的元素个数，M 是取出来的个数。也就是说，十几万人的名单，找起点只要十几二十步，之后只走被取出来的那几个。

## 六、不用 Redis，放在 Java 内存里也行

如果面试官问「不用 Redis 怎么做」，思路完全一样，把有序集合换成 `TreeMap`（按键排好序的 Map）：

```java
record Alert(long alertId, long userId) {}

class StockAlerts {
    /** 涨到名单：提醒价（分）→ 设了这个价的预警 */
    final TreeMap<Long, List<Alert>> rise = new TreeMap<>();
    /** 跌到名单 */
    final TreeMap<Long, List<Alert>> fall = new TreeMap<>();
}

/** 股票代码 → 这只股票的两张名单 */
Map<String, StockAlerts> index = new HashMap<>();

/** 行情到达：取出要提醒的预警，并从名单里删掉 */
List<Alert> onTick(String code, long priceFen) {
    StockAlerts s = index.get(code);
    if (s == null) {
        return Collections.emptyList();
    }
    List<Alert> hit = new ArrayList<>();
    // 涨到名单：提醒价 <= 现价
    NavigableMap<Long, List<Alert>> up = s.rise.headMap(priceFen, true);
    up.values().forEach(hit::addAll);
    up.clear();
    // 跌到名单：提醒价 >= 现价
    NavigableMap<Long, List<Alert>> down = s.fall.tailMap(priceFen, true);
    down.values().forEach(hit::addAll);
    down.clear();
    return hit;
}
```

- `headMap(价格, true)` 拿到「键 ≤ 价格」的那一段，`tailMap(价格, true)` 拿到「键 ≥ 价格」的那一段。对这一段调 `clear()`，会把原来 `TreeMap` 里的这些项一起删掉。
- 200 万条用 `TreeMap` 存，大约一两百 MB；如果只存「提醒价 + 预警编号」两个数字、用排好序的数组加二分查找，二三十 MB 就够。
- 同一只股票的行情和用户改预警，交给同一个线程处理（按股票代码取余选线程），`TreeMap` 就不用加锁。

三种放法怎么选：

| 放在哪 | 好处 | 问题 |
|---|---|---|
| Java 内存 | 最快，不依赖外部服务 | 多台机器各有一份，重启要从数据库重新加载 |
| Redis 有序集合 | 多台机器共用一份，重启不用重新加载 | 每次查询都要走网络 |
| 直接查 MySQL | 不用同步数据 | 每 3 秒 6000 次范围查询压在业务库上，大跌时一次返回几十万行 |

不管放在 Java 内存还是 Redis，规则都以 MySQL 为准；内存和 Redis 里的名单只是方便快速查询的副本，丢了可以从数据库重建。

## 七、常见追问

**价格在提醒价附近来回跳，会不会一直提醒？**

不会，取出来就删掉了。如果产品要求「每次涨过去都提醒」，就在价格离开提醒价一段距离后（比如回落 1%）再把这条预警放回名单，免得价格在线上来回跳时连续提醒。

**不删的话怎么查？**

记住每只股票上一次的价格，只取「上一次价格到这一次价格」之间的。涨了就在涨到名单里取「大于上一次、小于等于这一次」的，Redis 写成 `ZRANGEBYSCORE alert:rise:X (1015 1030`，左括号表示不包含 1015。

**用户设预警时，价格已经过了提醒价怎么办？**

设置时校验：「涨到」必须高于现价，「跌到」必须低于现价。如果产品允许，就在设好的那一刻判断一次，满足就马上提醒。

**用户改了、删了预警怎么办？**

改提醒价：对同一个成员再 `ZADD` 一次，分数就改了。删预警：`ZREM 键 成员`。「涨到」改成「跌到」：从一张名单删掉，再加到另一张。

**两台机器同时在查，会不会重复提醒？**

取出和删除在同一个 Lua 脚本里，同一条预警只有一台机器能取到。推送前还可以再加一道：`SET 已提醒:日期:预警编号 1 NX EX 86400`，写入成功才发（`NX` 表示键不存在才写，`EX 86400` 表示一天后自动删除）。

**Redis 数据丢了或者重启了怎么办？**

以 MySQL 里的预警表为准，每天开盘前重建所有名单。删旧名单用 `UNLINK` 而不是 `DEL`：一张十几万人的名单用 `DEL` 删，要逐个释放元素，会让 Redis 卡一下；`UNLINK` 只把键摘掉，内存交给后台线程慢慢释放。

**热门股一张名单十几万人，算不算大 key？**

大 key 指一个键下面数据特别多。按分数范围查不受影响，因为只走取出来的那几个；但不要整张名单一次读出来，也不要用 `DEL` 整张删。

**大跌时一轮触发几十万条怎么办？**

匹配出来的结果先写进消息队列排队，推送服务按自己的速度取；同一个用户同一轮触发多条，合成一条提醒；按推送通道的限制控制发送速度。

## 八、有序集合还能用在哪：8 个场景

### 怎么判断该用有序集合

题目里出现这些说法，就该想到它：

- 排行榜、前 N 名、我排第几
- 到点、到价、到量就触发
- 最近 N 条、按时间倒序、只留最新的
- 一段时间内有多少次
- 按某个数字的范围筛、找某个数落在哪一档

然后问自己三个问题：**成员是谁？分数是什么数字？是按排名取，还是按分数范围取？** 这三个问题答出来，方案就出来了。

| 场景 | 成员 | 分数 | 关键命令 |
|---|---|---|---|
| 股价预警（上面讲的） | 预警编号 + 用户编号 | 提醒价 | `ZRANGEBYSCORE`、`ZREMRANGEBYSCORE` |
| 1. 排行榜 | 用户 | 积分 | `ZINCRBY`、`ZREVRANGE`、`ZREVRANK` |
| 2. 订单超时取消 | 订单号 | 到期时间 | `ZRANGEBYSCORE`、`ZREM` |
| 3. 限流 | 请求编号 | 请求时间 | `ZREMRANGEBYSCORE`、`ZCARD` |
| 4. 最近浏览 | 商品 | 浏览时间 | `ZADD`、`ZREVRANGE`、`ZREMRANGEBYRANK` |
| 5. 时间线翻页 | 帖子 | 发布时间 | `ZREVRANGEBYSCORE … LIMIT` |
| 6. 优先级队列 | 任务 | 优先级 | `ZPOPMIN` |
| 7. 按区间找档位 | 档位名 | 档位起点 | `ZREVRANGEBYSCORE … LIMIT 0 1` |
| 8. 附近门店 | 门店 | 经纬度编出来的数字 | `GEOADD`、`GEOSEARCH` |

下面的时间都用时间戳表示，也就是从 1970 年 1 月 1 日开始数的毫秒数，一个整数。

### 1. 排行榜

游戏积分榜、直播间贡献榜：成员是用户，分数是积分。

```text
> ZADD 积分榜 120 小红 300 小明 80 小刚
3

# 小刚又得了 50 分，返回加完以后的分数
> ZINCRBY 积分榜 50 小刚
130

# 前 2 名，分数从高到低（REV 是 reverse，倒过来）
> ZREVRANGE 积分榜 0 1 WITHSCORES
小明 300
小刚 130

# 小红排第几：从 0 开始数，所以 2 表示第 3 名
> ZREVRANK 积分榜 小红
2
```

**要注意：分数相同时，不是谁先到谁排前面。** 小王、小李、阿强都是 100 分，从高到低取出来是「阿强、小王、小李」，按的是名字的字节顺序。要让先到的排前面，就把时间也编进分数：

> 分数 = 积分 × 10¹⁰ +（9999999999 − 达到这个积分时的秒数时间戳）

积分相同时，越早达到的，后半截越大，排在前面。加分时要重新算出整个分数再 `ZADD`。分数能精确表示的整数上限大约是 9 × 10¹⁵，所以积分要在 90 万以内。

### 2. 订单超时取消

下单 30 分钟没付款就自动取消：成员是订单号，分数是到期时间（下单时间 + 30 分钟）。定时任务每秒查一次「到期时间 ≤ 现在」的订单。

```text
> ZADD 待取消订单 1764000000000 订单A 1764000060000 订单B 1764000120000 订单C
3

# 现在是 1764000060000：已经到期的，一次最多取 100 个
> ZRANGEBYSCORE 待取消订单 0 1764000060000 LIMIT 0 100
订单A
订单B

# 谁删成功谁处理
> ZREM 待取消订单 订单A
1
# 另一台机器也想处理订单A，删的时候返回 0，跳过
> ZREM 待取消订单 订单A
0
```

**它和股价预警是同一个结构：一个是到价，一个是到点。**

要注意：多台机器都在跑这个定时任务，用 `ZREM` 的返回值决定谁来处理。真正取消订单时，订单表要用带条件的更新（`UPDATE … WHERE 状态 = 待支付`），防止用户刚好在这时付了款；另外定时扫一遍订单表，把 Redis 里漏掉的补上。

### 3. 限流：每个用户 1 分钟内最多 N 次

成员是这次请求的唯一编号，分数是请求时间。每来一个请求：先删掉 1 分钟以前的记录，数一下还剩几个，没到上限就把这次也记进去。三步要放进一个 Lua 脚本：

```lua
-- KEYS[1] = 这个用户的限流键
-- ARGV[1] = 现在（毫秒），ARGV[2] = 窗口长度（毫秒），ARGV[3] = 上限，ARGV[4] = 这次请求的唯一编号
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, ARGV[1] - ARGV[2])
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then
    return 0
end
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[4])
redis.call('PEXPIRE', KEYS[1], ARGV[2])
return 1
```

上限设成 3 次，看一个用户的请求：

| 请求时间 | 删掉多久以前的 | 剩下几个 | 结果 |
|---|---|---|---|
| 第 0 秒 | — | 0 | 放行 |
| 第 10 秒 | — | 1 | 放行 |
| 第 20 秒 | — | 2 | 放行 |
| 第 30 秒 | — | 3 | 拒绝 |
| 第 65 秒 | 第 5 秒以前（删掉第 0 秒那次） | 2 | 放行 |

这叫**滑动窗口**：窗口跟着当前时间往后滑，统计的永远是「最近 60 秒」。如果改成「每到整分钟清零重数」，用户在第 59 秒来 3 次、第 61 秒再来 3 次，2 秒内就放过了 6 次。

要注意：每个请求在名单里占一行，上限很大（比如 1 分钟 1 万次）时太占内存，这种情况换成只记一个数字的计数器。

### 4. 最近浏览

商品浏览记录要去重、按时间从新到旧排、只留最新的 100 条：成员是商品，分数是浏览时间（下面简写成 1001、1002）。

```text
> ZADD 浏览:用户1 1001 商品A 1002 商品B 1003 商品C
3

# 又看了一次商品A：成员已经存在，只更新时间，不会多一条
> ZADD 浏览:用户1 1004 商品A
0

# 按时间从新到旧
> ZREVRANGE 浏览:用户1 0 -1
商品A
商品C
商品B

# 只留最新 2 条：排名从 0 开始、从分数最小（最旧）的数起，-1 是最新的一条，
# 0 到 -3 就是「除了最新 2 条以外的全部」
> ZREMRANGEBYRANK 浏览:用户1 0 -3
1
```

实际只留 100 条，就写 `ZREMRANGEBYRANK 浏览:用户1 0 -101`。用 List 也能存浏览记录，但重复看的商品要自己找出来删掉；有序集合靠「成员不能重复」自动去重。

### 5. 时间线翻页

关注的人发的帖子按时间倒序，往下滑加载下一页：成员是帖子，分数是发布时间（下面简写成 100、200……）。

按排名翻页（第 1 页取第 0、1 条，第 2 页取第 2、3 条）有个问题：刷的过程中来了新帖子，所有帖子往后挪一位，第 2 页会重复看到第 1 页的最后一条。

```text
> ZADD 时间线 100 帖1 200 帖2 300 帖3 400 帖4 500 帖5
5

# 第 1 页
> ZREVRANGEBYSCORE 时间线 +inf -inf LIMIT 0 2
帖5
帖4

# 这时来了一条新帖
> ZADD 时间线 600 帖6
1

# 按排名取第 2 页：帖4 又出现了一次
> ZREVRANGE 时间线 2 3
帖4
帖3

# 按时间取第 2 页：从上一页最后一条的时间（400）接着往下取，( 表示不包含 400
> ZREVRANGEBYSCORE 时间线 (400 -inf LIMIT 0 2
帖3
帖2
```

客户端每次把这一页最后一条的时间带回来，下一页从它接着取，新帖子插进来也不会重复。要注意：两条帖子时间完全一样时可能漏掉一条，时间用到毫秒基本不会撞上。

### 6. 优先级队列

VIP 工单先处理：成员是工单，分数是优先级，数字越小越先处理。

```text
> ZADD 工单 1 VIP工单 5 普通工单1 5 普通工单2
3

# 取出并删除分数最小的一个
> ZPOPMIN 工单
VIP工单 1
> ZPOPMIN 工单
普通工单1 5
```

`ZPOPMIN`（Redis 5.0 起有）把「取」和「删」一步做完，多个处理线程同时取，不会拿到同一个。还有一个会等待的版本 `BZPOPMIN`：队列空的时候先等着，有了再返回。

### 7. 按区间找档位

会员等级：0 积分起是普通，1000 起是银卡，5000 起是金卡。成员是等级名，分数是这一档的起点。找一个积分属于哪一档，就是找「起点 ≤ 这个积分」里最大的那个：

```text
> ZADD 会员等级 0 普通 1000 银卡 5000 金卡
3

# 3200 积分：从高往低找，第一个起点 ≤ 3200 的
> ZREVRANGEBYSCORE 会员等级 3200 -inf LIMIT 0 1
银卡

# 价格在 100 到 200 之间的商品
> ZADD 商品价格 99 商品1 150 商品2 199 商品3 260 商品4
4
> ZRANGEBYSCORE 商品价格 100 200
商品2
商品3
```

同一个套路还能用在：运费按重量分档、个税按收入分档、按 IP 地址查归属地（把每个 IP 段的起点转成整数当分数，找「起点 ≤ 这个 IP」的最后一段）。

### 8. 附近门店

成员是门店，分数是把经纬度编出来的一个数字。

```text
> GEOADD 门店 116.397 39.908 门店A 116.326 39.992 门店B 116.481 39.990 门店C
3

# 这个位置 5 公里以内的门店，近的在前，带上距离（公里）
> GEOSEARCH 门店 FROMLONLAT 116.40 39.91 BYRADIUS 5 km ASC WITHDIST
门店A 0.3391

# GEO 存的就是一个有序集合
> TYPE 门店
zset
```

GEO 这组命令底层就是有序集合：把经度和纬度的二进制位交错拼成一个 52 位的整数当分数（这种编码叫 geohash）。离得近的点，编出来的数字也接近，「找附近」就变成了按分数范围找；查的时候 Redis 会把周围 8 块区域一起查，免得漏掉正好在边界另一侧的点。也正因为是有序集合，GEO 没有专门的删除命令，删门店直接用 `ZREM`。

### 什么时候不该用有序集合

- **要按多个条件组合查**：价格 100 到 200、某个品牌、有货。有序集合只能按一个分数查，这种交给数据库或搜索引擎。
- **单张名单太大**：几千万个成员挤在一个键里，迁移、删除、备份都慢。按某个维度拆成多个键，比如按股票、按日期。
- **数据丢不起**：有序集合只当方便快速查询的副本，以数据库为准，丢了能重建。

## 九、面试时可以这样说

「先把用户的条件统一换算成提醒价，涨幅跌幅用昨收在开盘前算好。每只股票两个有序集合，一个存涨到、一个存跌到，成员是『预警编号 : 用户编号』，分数是提醒价（分）。行情来了，涨到组取提醒价 ≤ 现价的，跌到组取提醒价 ≥ 现价的，取出来的就是要提醒的用户，同时删掉，当天不再提醒；取出和删除放在一个 Lua 脚本里，避免重复和漏掉。有序集合底层是跳表加哈希表，按分数范围查是 O(log N + M)，十几万人的热门股，找起点也只要十几二十步。200 万条放 Redis 大约两百 MB；不用 Redis 的话，换成 Java 的 TreeMap，思路一样。」

遇到别的题，先问那三个问题：成员是谁？分数是什么数字？按排名取还是按分数范围取？排行榜、订单超时取消、限流、按区间找档位，都能这样套出来。
