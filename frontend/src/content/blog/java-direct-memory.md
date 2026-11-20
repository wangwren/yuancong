---
title: Java 直接内存：它是什么、为什么要有、平时在哪用到
description: 用直接内存复制文件为什么更快、它怎么溢出、怎么被释放、禁用 System.gc() 会出什么问题，以及 5 个实际会碰到它的场景。
pubDate: 2026-11-19
tags: [Java]
---

直接内存平时写业务代码很少碰到，但面试常问，线上出了问题也不好查：堆明明没满，进程却报内存溢出，或者容器里的服务被系统直接杀掉。

## 一、先跑个实验：同一个文件，三种复制写法

复制文件最常见的写法，是用 `FileInputStream` 和 `FileOutputStream`，中间用一个 `byte[]` 当缓冲区，读一块、写一块：

```java
try (FileInputStream in = new FileInputStream(src);
     FileOutputStream out = new FileOutputStream(dst)) {
    byte[] buf = new byte[1024 * 1024];   // 每次搬 1MB
    int n;
    while ((n = in.read(buf)) != -1) {
        out.write(buf, 0, n);
    }
}
```

Java 1.4 起还有另一套读写方式，叫 NIO。它用 `FileChannel`（负责读写文件的通道）代替输入输出流，用 `ByteBuffer`（一块装数据的缓冲区，作用和上面的 `byte[]` 一样）代替数组。`ByteBuffer` 有两种申请方法：

```java
ByteBuffer.allocate(1024 * 1024);        // 普通缓冲区
ByteBuffer.allocateDirect(1024 * 1024);  // 直接缓冲区
```

用 NIO 复制文件：

```java
try (FileChannel from = new FileInputStream(src).getChannel();
     FileChannel to = new FileOutputStream(dst).getChannel()) {
    ByteBuffer buf = ByteBuffer.allocateDirect(1024 * 1024);   // 换成 allocate 就是普通缓冲区
    while (from.read(buf) != -1) {
        buf.flip();                       // 切换成「读出」模式
        while (buf.hasRemaining()) {
            to.write(buf);
        }
        buf.clear();                      // 清空，下一轮接着用
    }
}
```

复制一个 1GB 的文件，三种写法各跑 15 次，取中位数：

| 写法 | JDK 8 | JDK 21 |
|---|---|---|
| `FileInputStream` + `byte[]` | 282 ms | 283 ms |
| `FileChannel` + `allocate()` 普通缓冲区 | 276 ms | 282 ms |
| `FileChannel` + `allocateDirect()` 直接缓冲区 | **239 ms** | **239 ms** |

只把 `allocate` 换成 `allocateDirect`，就快了 40 毫秒左右，大约 15%，JDK 8 和 21 结果一样。差距大小和磁盘、文件当时是否已经在内存里有关，有的环境下能差好几倍。

这 40 毫秒省在哪里，要从读文件时数据怎么走说起。

## 二、为什么快：数据少复制了一次

### 读文件时，数据要走几步

Java 程序自己碰不到磁盘。读文件时，数据是这样走的：

1. 操作系统把磁盘上的数据读进它自己管理的一块内存，叫**系统缓冲区**。Java 代码不能直接访问这块内存。
2. Java 调用操作系统提供的读函数（这叫**系统调用**），告诉它：把数据复制到这个地址来。操作系统就把数据从系统缓冲区复制到 Java 给的地址。

问题来了：Java 该给哪个地址？

### 为什么不能直接给堆里的地址

普通缓冲区（`allocate` 出来的 `ByteBuffer`，或者 `byte[]`）放在堆里。堆是 GC（垃圾回收）管的区域。GC 回收完垃圾后，为了不留下零零碎碎的空隙，会把还活着的对象挪到一起。挪完以后，对象的地址就变了。

<figure class="fig">
<div class="fig-box">
<svg viewBox="0 0 720 210" role="img" aria-label="GC 整理前后，对象 B 和 C 的地址发生变化">
<defs><marker id="dm1-a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah-pri" d="M0 0L10 5L0 10z"/></marker></defs>
<text class="t-b" x="20" y="46">GC 前</text>
<rect class="bx-heap" x="110" y="16" width="112" height="50" rx="8"/>
<text class="t-b" x="166" y="38" text-anchor="middle">A</text>
<text class="t-s" x="166" y="57" text-anchor="middle">地址 100</text>
<rect class="bx-dim" x="230" y="16" width="112" height="50" rx="8"/>
<text class="t-s" x="286" y="46" text-anchor="middle">垃圾</text>
<rect class="bx-heap" x="350" y="16" width="112" height="50" rx="8"/>
<text class="t-b" x="406" y="38" text-anchor="middle">B</text>
<text class="t-s" x="406" y="57" text-anchor="middle">地址 300</text>
<rect class="bx-dim" x="470" y="16" width="112" height="50" rx="8"/>
<text class="t-s" x="526" y="46" text-anchor="middle">垃圾</text>
<rect class="bx-heap" x="590" y="16" width="112" height="50" rx="8"/>
<text class="t-b" x="646" y="38" text-anchor="middle">C</text>
<text class="t-s" x="646" y="57" text-anchor="middle">地址 500</text>
<path class="ln ln-pri" d="M406 68L290 136" marker-end="url(#dm1-a)"/>
<path class="ln ln-pri" d="M646 68L410 136" marker-end="url(#dm1-a)"/>
<text class="t-b t-pri" x="110" y="108">B、C 的地址都变了</text>
<text class="t-b" x="20" y="170">GC 后</text>
<rect class="bx-heap" x="110" y="140" width="112" height="50" rx="8"/>
<text class="t-b" x="166" y="162" text-anchor="middle">A</text>
<text class="t-s" x="166" y="181" text-anchor="middle">地址 100</text>
<rect class="bx-heap" x="230" y="140" width="112" height="50" rx="8"/>
<text class="t-b" x="286" y="162" text-anchor="middle">B</text>
<text class="t-s" x="286" y="181" text-anchor="middle">地址 200</text>
<rect class="bx-heap" x="350" y="140" width="112" height="50" rx="8"/>
<text class="t-b" x="406" y="162" text-anchor="middle">C</text>
<text class="t-s" x="406" y="181" text-anchor="middle">地址 300</text>
<rect class="bx-dim" x="470" y="140" width="112" height="50" rx="8"/>
<text class="t-s" x="526" y="170" text-anchor="middle">空闲</text>
<rect class="bx-dim" x="590" y="140" width="112" height="50" rx="8"/>
<text class="t-s" x="646" y="170" text-anchor="middle">空闲</text>
</svg>
</div>
<figcaption>图 1　GC 整理内存时会挪动还活着的对象，挪完地址就变了</figcaption>
</figure>

操作系统复制数据是要花时间的。如果复制到一半，GC 把这个数组挪走了，数据就写到别的地方去了。所以 JVM 不会把堆里的地址交给操作系统，而是分三步走：

1. 先在堆外面拿一块临时内存。堆外的内存 GC 不管，地址不会变；
2. 让操作系统把数据复制到这块临时内存；
3. 再从临时内存复制到堆里的缓冲区。

第 3 步就是多出来的那次复制。NIO 读文件的这段逻辑在 JDK 的 `sun.nio.ch.IOUtil.read` 里（JDK 21，有删减）：

```java
static int read(FileDescriptor fd, ByteBuffer dst, ...) {
    if (dst instanceof DirectBuffer) {
        // 直接缓冲区：本来就在堆外，让操作系统直接写进来
        return readIntoNativeBuffer(fd, dst, ...);
    }
    // 普通缓冲区：先拿一块临时的堆外内存
    ByteBuffer bb = Util.getTemporaryDirectBuffer(rem);
    try {
        int n = readIntoNativeBuffer(fd, bb, ...);   // 操作系统把数据写进临时内存
        bb.flip();
        if (n > 0)
            dst.put(bb);                             // 再复制回堆里，这就是多出来的那次
        return n;
    } finally {
        Util.offerFirstTemporaryDirectBuffer(bb);    // 临时内存用完放回缓存（场景 1 会讲到）
    }
}
```

写文件反过来走一遍，也多一次复制（`IOUtil.write`）。`FileInputStream` 也是同样的道理：读超过 8KB 的数据时，JVM 先在 C 代码里用 `malloc` 申请一块临时内存让操作系统写进去，再复制到 Java 的 `byte[]`（JDK 源码 `io_util.c`）。

<figure class="fig">
<div class="fig-box">
<svg viewBox="0 0 720 276" role="img" aria-label="用普通缓冲区读文件比直接缓冲区多复制一次">
<defs><marker id="dm2-a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah" d="M0 0L10 5L0 10z"/></marker><marker id="dm2-s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah-sec" d="M0 0L10 5L0 10z"/></marker></defs>
<text class="t-b" x="10" y="28">普通缓冲区 allocate()：数据最后放在堆里</text>
<rect class="bx-dim" x="10" y="42" width="120" height="62" rx="8"/>
<text x="70" y="78" text-anchor="middle">磁盘</text>
<rect class="bx" x="170" y="42" width="150" height="62" rx="8"/>
<text x="245" y="68" text-anchor="middle">系统缓冲区</text>
<text class="t-s" x="245" y="90" text-anchor="middle">Java 代码碰不到</text>
<rect class="bx-off" x="360" y="42" width="150" height="62" rx="8"/>
<text x="435" y="68" text-anchor="middle">临时堆外内存</text>
<text class="t-s" x="435" y="90" text-anchor="middle">JDK 自动申请</text>
<rect class="bx-heap" x="550" y="42" width="160" height="62" rx="8"/>
<text x="630" y="68" text-anchor="middle">堆里的缓冲区</text>
<text class="t-s" x="630" y="90" text-anchor="middle">Java 代码读这里</text>
<path class="ln" d="M130 73H166" marker-end="url(#dm2-a)"/>
<path class="ln" d="M320 73H356" marker-end="url(#dm2-a)"/>
<path class="ln ln-sec" d="M510 73H546" marker-end="url(#dm2-s)"/>
<text class="t-s" x="340" y="128" text-anchor="middle">系统调用</text>
<text class="t-b t-sec" x="528" y="128" text-anchor="middle">多复制一次</text>
<text class="t-b" x="10" y="168">直接缓冲区 allocateDirect()：数据就放在堆外</text>
<rect class="bx-dim" x="10" y="182" width="120" height="62" rx="8"/>
<text x="70" y="218" text-anchor="middle">磁盘</text>
<rect class="bx" x="170" y="182" width="150" height="62" rx="8"/>
<text x="245" y="208" text-anchor="middle">系统缓冲区</text>
<text class="t-s" x="245" y="230" text-anchor="middle">Java 代码碰不到</text>
<rect class="bx-off" x="360" y="182" width="350" height="62" rx="8"/>
<text x="535" y="208" text-anchor="middle">直接内存</text>
<text class="t-s" x="535" y="230" text-anchor="middle">地址固定：操作系统直接写进来，Java 代码也直接读这里</text>
<path class="ln" d="M130 213H166" marker-end="url(#dm2-a)"/>
<path class="ln" d="M320 213H356" marker-end="url(#dm2-a)"/>
<text class="t-s" x="340" y="268" text-anchor="middle">系统调用</text>
</svg>
</div>
<figcaption>图 2　读文件的两条路：普通缓冲区比直接缓冲区多一次「堆外 → 堆」的复制</figcaption>
</figure>

复制文件是先读后写，读和写各多复制一次。1GB 的文件就要在内存里多搬 2GB 数据，这就是第一节实验里差出来的那 40 毫秒左右。

### 所以，直接内存是什么

**用 `allocateDirect` 申请的缓冲区，数据放在堆外的一块内存里。这块内存地址固定，操作系统可以直接往里读写，Java 代码也能直接访问它。这块不在堆里、Java 代码和操作系统都能直接用的内存，就是直接内存。**

JDK 的 `ByteBuffer` 文档也是这么说的：对直接缓冲区，JVM 会尽量直接在它上面做读写，避免每次调用操作系统的读写前后，把内容复制到一块中间缓冲区。

它也有代价。同一份文档写着：直接缓冲区的申请和释放成本通常比普通缓冲区高；所以**建议主要给大的、长期使用的、要交给操作系统读写的缓冲区用**，只有能测出性能提升时才用。换成做法就是一句话：**申请一次，反复用**。上面复制文件的代码里，缓冲区就是循环外申请一次，每一轮 `clear()` 以后接着用。

注意，省掉的只是「堆外 → 堆」这一次。磁盘到系统缓冲区、系统缓冲区到直接内存这两段还在。让文件内容从磁盘直接送到网络、完全不经过 Java 程序的做法叫「零拷贝」（Java 里是 `FileChannel.transferTo`），那是另一回事。

## 三、它在哪、有多大

### allocateDirect 返回的对象在哪

```java
ByteBuffer directBuf = ByteBuffer.allocateDirect(1024);
```

这一行代码做了两件事：

1. 在堆外申请 1024 字节内存，**数据存在这里**；
2. 在堆里创建一个 Java 对象，类型是 `DirectByteBuffer`，变量 `directBuf` 指向它。**这个对象不存数据，只记着堆外那块内存的地址和大小**，所以它本身只占几十字节。

调用 `directBuf.put()`、`directBuf.get()` 时，这个对象按记下的地址去堆外读写。

<figure class="fig">
<div class="fig-box">
<svg viewBox="0 0 720 306" role="img" aria-label="一个 Java 进程的内存：堆、直接内存、元空间、线程栈、代码缓存">
<defs><marker id="dm3-a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah-sec" d="M0 0L10 5L0 10z"/></marker></defs>
<text class="t-b" x="20" y="26">一个 Java 进程实际占用的内存</text>
<rect class="bx ln-dash" x="10" y="38" width="700" height="234" rx="14"/>
<rect class="bx-heap" x="26" y="54" width="272" height="202" rx="10"/>
<text class="t-b t-pri" x="42" y="80">堆（-Xmx）</text>
<text class="t-s" x="42" y="100">new 出来的对象，GC 负责清理</text>
<rect class="bx" x="42" y="116" width="34" height="24" rx="5"/>
<rect class="bx" x="86" y="116" width="52" height="24" rx="5"/>
<rect class="bx" x="148" y="116" width="28" height="24" rx="5"/>
<rect class="bx" x="186" y="116" width="44" height="24" rx="5"/>
<rect class="bx" x="42" y="150" width="60" height="24" rx="5"/>
<rect class="bx" x="112" y="150" width="30" height="24" rx="5"/>
<rect class="bx" x="42" y="186" width="230" height="56" rx="8"/>
<text x="56" y="208">DirectByteBuffer 对象</text>
<text class="t-s" x="56" y="229">只记着堆外内存的地址和大小</text>
<text class="t-b t-sec" x="320" y="80">堆外内存（堆以外的都算）</text>
<rect class="bx-off" x="320" y="96" width="240" height="160" rx="10"/>
<text class="t-b" x="336" y="122">直接内存</text>
<text class="t-s" x="336" y="146">数据实际放在这里</text>
<text class="t-s" x="336" y="168">上限 -XX:MaxDirectMemorySize</text>
<text class="t-s" x="336" y="190">不设时约等于 -Xmx</text>
<rect class="bx-dim" x="572" y="96" width="126" height="46" rx="8"/>
<text x="635" y="124" text-anchor="middle">元空间</text>
<rect class="bx-dim" x="572" y="153" width="126" height="46" rx="8"/>
<text x="635" y="181" text-anchor="middle">线程栈</text>
<rect class="bx-dim" x="572" y="210" width="126" height="46" rx="8"/>
<text x="635" y="238" text-anchor="middle">代码缓存等</text>
<path class="ln ln-sec" d="M272 214H316" marker-end="url(#dm3-a)"/>
<text class="t-s" x="20" y="296">放进容器时，容器的内存上限要比这些加起来还大，只算 -Xmx 是不够的</text>
</svg>
</div>
<figcaption>图 3　directBuf 指向的对象在堆里，真正的数据在堆外的直接内存里</figcaption>
</figure>

一个 Java 进程向操作系统要的内存，不止堆这一块：类的信息放在元空间，每个线程有自己的线程栈，JVM 运行中把经常执行的方法编译成机器码，放在代码缓存。这些都在堆外面，统称「堆外内存」。**直接内存是堆外内存的一种**，也是最常见的一种，平时说「堆外内存溢出」，多数指的就是它。

### 上限是多少

用 `-XX:MaxDirectMemorySize` 设。不设的话，上限等于 `Runtime.getRuntime().maxMemory()`，大约就是 `-Xmx`。

比如只给 `-Xmx256m`、不设上限，在 JDK 21 上申请 1GB 直接内存，会报：

```text
OutOfMemoryError: Cannot reserve 1073741824 bytes of direct buffer memory (allocated: 0, limit: 268435456)
```

`limit: 268435456` 正好是 256MB，跟 `-Xmx` 一样。

网上有文章说默认是 64MB，这个说法来自源码里的一个初始值。JDK 21 的 `jdk.internal.misc.VM`：

```java
// The initial value of this field is arbitrary; during JRE initialization
// it will be reset to the value specified on the command line, if any,
// otherwise to Runtime.getRuntime().maxMemory().
private static long directMemory = 64 * 1024 * 1024;
```

注释写得很清楚：64MB 只是随便给的初始值，JVM 启动时会被覆盖成命令行设的值，没设就用 `Runtime.getRuntime().maxMemory()`。JDK 8 的 `sun.misc.VM` 是同样的写法。

另外要注意：**直接内存不省内存。** 它是 `-Xmx` 之外的额外占用，图 3 里的每一块都算在进程占用的内存里。

## 四、直接内存溢出

一直申请直接内存、一直不放手，会怎样？

```java
List<ByteBuffer> list = new ArrayList<>();
int i = 0;
try {
    while (true) {
        list.add(ByteBuffer.allocateDirect(100 * 1024 * 1024));   // 每次 100MB，都存进 list 不放手
        i++;
    }
} finally {
    System.out.println("成功申请了 " + i + " 次");
}
```

用 `-Xmx256m -XX:MaxDirectMemorySize=1g` 运行，两个版本都是申请成功 10 次（1000MB），第 11 次失败：

| JDK | 报错 |
|---|---|
| 8 | `java.lang.OutOfMemoryError: Direct buffer memory` |
| 21 | `java.lang.OutOfMemoryError: Cannot reserve 104857600 bytes of direct buffer memory (allocated: 1048576000, limit: 1073741824)` |

和堆溢出的报错（`Java heap space`）不一样。看到 `Direct buffer memory` 就知道是直接内存不够了。而这时堆的上限只有 256MB，里面也只有 10 个 `DirectByteBuffer` 小对象，几乎是空的。

这个例子是「一直在用、不放手」，溢出是理所当然的。线上更常见的情况是**明明已经不用了，内存却迟迟没有释放**。要弄懂这个，得先看直接内存是怎么释放的。

## 五、它是怎么被释放的

### 先看现象

申请 1GB 直接内存，然后不再引用它，再调用 `System.gc()`，每一步都看看进程实际占用的内存（`ps` 命令的 RSS，即真正占用的物理内存）：

```java
ByteBuffer buf = ByteBuffer.allocateDirect(1024 * 1024 * 1024);   // 1GB
buf = null;
System.gc();
```

| 步骤 | JDK 8 | JDK 21 |
|---|---|---|
| 开始 | 38 MB | 47 MB |
| 申请 1GB 之后 | 1064 MB | 1074 MB |
| `buf = null` 之后 | 1064 MB | 1074 MB |
| `System.gc()` 之后 | **42 MB** | **49 MB** |

（运行参数 `-Xmx256m -XX:MaxDirectMemorySize=2g`。）

两个现象：

1. `buf = null` 之后，内存一点没少。**不用了不等于释放了。**
2. `System.gc()` 之后，1GB 回来了。

奇怪的地方在第 2 点：GC 只清理堆里的对象，它是怎么把堆外的 1GB 也释放掉的？

### 真正申请和释放内存的是 Unsafe

JDK 里有一个内部类 `sun.misc.Unsafe`，能直接向操作系统申请和释放内存，有点像 C 语言的 `malloc` 和 `free`。它是 JDK 内部用的类，业务代码不要直接用：

```java
Field f = Unsafe.class.getDeclaredField("theUnsafe");   // Unsafe 不让直接 new，用反射拿
f.setAccessible(true);
Unsafe unsafe = (Unsafe) f.get(null);

long size = 1024L * 1024 * 1024;
long address = unsafe.allocateMemory(size);   // 申请 1GB，拿到的是一个地址
unsafe.setMemory(address, size, (byte) 0);    // 全部写一遍 0，让操作系统真正分配
unsafe.freeMemory(address);                   // 手动释放
```

| 步骤 | JDK 8 | JDK 21 |
|---|---|---|
| 开始 | 38 MB | 47 MB |
| `allocateMemory` 之后 | 1064 MB | 1074 MB |
| `freeMemory` 之后 | 40 MB | 50 MB |

用 `Unsafe` 申请的内存，只有调用 `freeMemory` 才会释放，GC 完全不管。另外，用 `Unsafe` 直接申请的内存不经过 JDK 的记账，既不受 `-XX:MaxDirectMemorySize` 限制，也不会出现在直接内存的统计里。

### allocateDirect 里面做了什么

`allocateDirect` 背后就是用 `Unsafe` 申请的。JDK 21 `DirectByteBuffer` 的构造方法（有删减）：

```java
DirectByteBuffer(int cap) {
    Bits.reserveMemory(size, cap);            // 1. 记账：总量会不会超过上限
    base = UNSAFE.allocateMemory(size);       // 2. 用 Unsafe 向操作系统申请内存
    UNSAFE.setMemory(base, size, (byte) 0);   //    并全部清零
    cleaner = Cleaner.create(this, new Deallocator(base, size, cap));   // 3. 登记释放任务
}
```

申请是第 2 步，释放靠的是第 3 步。这一行做了两件事：

- **`Deallocator` 是一个释放任务**，里面就是调用 `freeMemory`：

```java
private record Deallocator(long address, long size, int capacity) implements Runnable {
    public void run() {
        UNSAFE.freeMemory(address);              // 释放堆外内存
        Bits.unreserveMemory(size, capacity);    // 记账：把额度还回去
    }
}
```

- **`Cleaner` 负责在合适的时候执行这个任务。** `Cleaner` 是一个「虚引用」（`PhantomReference`）。虚引用是 Java 里一种特殊的引用，它不会阻止对象被回收，唯一的作用是：**它关联的对象被 GC 回收以后，它会收到通知。** 这里关联的就是 `this`，也就是第三节说的那个堆里的 `DirectByteBuffer` 对象。

收到通知以后，谁来执行释放任务？JVM 里有一个专门的后台线程，叫 **Reference Handler**，负责处理这些通知。它发现收到通知的是一个 `Cleaner`，就调用它的 `clean()` 方法，`clean()` 再执行 `Deallocator`。这段逻辑在 `java.lang.ref.Reference` 里：

```java
if (ref instanceof Cleaner) {
    ((Cleaner) ref).clean();
}
```

把整条链串起来：

<figure class="fig">
<div class="fig-box">
<svg viewBox="0 0 720 256" role="img" aria-label="直接内存释放的完整链条">
<defs><marker id="dm4-a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah" d="M0 0L10 5L0 10z"/></marker></defs>
<rect class="bx-heap" x="10" y="20" width="210" height="70" rx="8"/>
<text class="t-b" x="115" y="49" text-anchor="middle">① 代码不再引用</text>
<text class="t-s" x="115" y="72" text-anchor="middle">buf = null</text>
<rect class="bx-heap" x="255" y="20" width="210" height="70" rx="8"/>
<text class="t-b" x="360" y="49" text-anchor="middle">② GC 回收这个对象</text>
<text class="t-s" x="360" y="72" text-anchor="middle">堆里的 DirectByteBuffer</text>
<rect class="bx" x="500" y="20" width="210" height="70" rx="8"/>
<text class="t-b" x="605" y="49" text-anchor="middle">③ Cleaner 收到通知</text>
<text class="t-s" x="605" y="72" text-anchor="middle">关联这个对象的虚引用</text>
<rect class="bx" x="500" y="140" width="210" height="70" rx="8"/>
<text class="t-b" x="605" y="169" text-anchor="middle">④ 后台线程处理</text>
<text class="t-s" x="605" y="192" text-anchor="middle">Reference Handler 调 clean()</text>
<rect class="bx-off" x="255" y="140" width="210" height="70" rx="8"/>
<text class="t-b" x="360" y="169" text-anchor="middle">⑤ 执行释放任务</text>
<text class="t-s" x="360" y="192" text-anchor="middle">Deallocator 调 freeMemory</text>
<rect class="bx-dim" x="10" y="140" width="210" height="70" rx="8"/>
<text class="t-b" x="115" y="169" text-anchor="middle">堆外 1GB 还回去了</text>
<text class="t-s" x="115" y="192" text-anchor="middle">进程内存 1074MB → 49MB</text>
<path class="ln" d="M220 55H251" marker-end="url(#dm4-a)"/>
<path class="ln" d="M465 55H496" marker-end="url(#dm4-a)"/>
<path class="ln" d="M605 90V136" marker-end="url(#dm4-a)"/>
<path class="ln" d="M500 175H469" marker-end="url(#dm4-a)"/>
<path class="ln" d="M255 175H224" marker-end="url(#dm4-a)"/>
<text class="t-sec" x="10" y="244">① 到 ② 之间要等多久，取决于 GC 什么时候来；堆很空闲时，可能很久都不来</text>
</svg>
</div>
<figcaption>图 4　从「不再引用」到「内存真正释放」的完整过程（JDK 8 和 21 都是这条链，类名略有不同）</figcaption>
</figure>

这就解释了前面的现象：`buf = null` 之后，堆里那个 `DirectByteBuffer` 对象还没被 GC 回收，链条停在第 ① 步，所以内存没少；`System.gc()` 触发了 GC，对象被回收，后面几步接着走完，1GB 就回来了。

总结成一句话：**直接内存什么时候释放，取决于堆里那个 `DirectByteBuffer` 对象什么时候被 GC 回收。**

问题也就出在这里。这个对象只有几十字节，对堆的占用几乎可以忽略，不会因为它触发 GC。如果堆很空闲，GC 很久才来一次，那些已经没人用的大块直接内存就一直占着。**堆看着很空，直接内存却已经满了。**

## 六、禁用显式回收的影响

在代码里主动调用 `System.gc()`，叫「显式回收」。很多线上服务会加上 `-XX:+DisableExplicitGC`，让 `System.gc()` 不起作用。原因是 `System.gc()` 默认会触发一次 Full GC（把整个堆回收一遍，期间程序会停顿），怕有人在代码里乱调。

这个参数会从两个地方影响直接内存。

### 影响一：手动 System.gc() 不管用了

把第五节的实验加上 `-XX:+DisableExplicitGC` 再跑一遍：

| 步骤 | JDK 8 | JDK 21 |
|---|---|---|
| 申请 1GB 之后 | 1063 MB | 1073 MB |
| `buf = null` 之后 | 1063 MB | 1073 MB |
| `System.gc()` 之后 | **1064 MB** | **1074 MB** |

`System.gc()` 没起作用，图 4 的链条停在第 ① 步，1GB 一直占着，要等某次 GC 自己发生才会释放。

### 影响二：JDK 自己的补救也失效了

JDK 其实考虑到了「堆很空、GC 不来」的问题。每次 `allocateDirect` 的第 1 步「记账」（`Bits.reserveMemory`）发现额度不够时，不会马上报错，而是按顺序再试几次：

<figure class="fig">
<div class="fig-box">
<svg viewBox="0 0 720 272" role="img" aria-label="Bits.reserveMemory 额度不够时的重试流程">
<defs><marker id="dm5-a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah" d="M0 0L10 5L0 10z"/></marker></defs>
<rect class="bx" x="10" y="20" width="150" height="50" rx="8"/>
<text x="85" y="50" text-anchor="middle">申请直接内存</text>
<rect class="bx" x="210" y="20" width="170" height="50" rx="8"/>
<text x="295" y="50" text-anchor="middle">额度还够吗？</text>
<rect class="bx" x="440" y="20" width="150" height="50" rx="8"/>
<text x="515" y="50" text-anchor="middle">够：直接分配</text>
<path class="ln" d="M160 45H206" marker-end="url(#dm5-a)"/>
<path class="ln" d="M380 45H436" marker-end="url(#dm5-a)"/>
<text class="t-s" x="408" y="36" text-anchor="middle">够</text>
<path class="ln" d="M295 70V98H90V126" marker-end="url(#dm5-a)"/>
<text class="t-s" x="306" y="92">不够</text>
<rect class="bx" x="10" y="130" width="160" height="64" rx="8"/>
<text class="t-b" x="90" y="156" text-anchor="middle">① 等释放任务</text>
<text class="t-s" x="90" y="178" text-anchor="middle">已收到通知的先释放</text>
<rect class="bx" x="190" y="130" width="160" height="64" rx="8"/>
<text class="t-b" x="270" y="156" text-anchor="middle">② System.gc()</text>
<text class="t-s" x="270" y="178" text-anchor="middle">主动触发一次 GC</text>
<rect class="bx" x="370" y="130" width="160" height="64" rx="8"/>
<text class="t-b" x="450" y="156" text-anchor="middle">③ 睡一会再试</text>
<text class="t-s" x="450" y="178" text-anchor="middle">间隔翻倍，最多 9 次</text>
<rect class="bx-off" x="550" y="130" width="160" height="64" rx="8"/>
<text class="t-b t-sec" x="630" y="156" text-anchor="middle">抛 OOM</text>
<text class="t-s" x="630" y="178" text-anchor="middle">Direct buffer memory</text>
<path class="ln" d="M170 162H186" marker-end="url(#dm5-a)"/>
<path class="ln" d="M350 162H366" marker-end="url(#dm5-a)"/>
<path class="ln" d="M530 162H546" marker-end="url(#dm5-a)"/>
<path class="ln ln-sec ln-dash" d="M270 196V214"/>
<text class="t-sec" x="270" y="234" text-anchor="middle">加了 -XX:+DisableExplicitGC，这一步不起作用</text>
<text class="t-s" x="10" y="262">每一步做完都会再试一次，额度够了就直接分配，不会走到下一步</text>
</svg>
</div>
<figcaption>图 5　额度不够时的重试顺序（JDK 21 Bits.reserveMemory；JDK 8 同样有 System.gc() 和最多 9 次的重试）</figcaption>
</figure>

1. 先等那些已经收到通知的释放任务执行完，看能不能腾出额度；
2. 还不够，调一次 `System.gc()`，让没人用的 `DirectByteBuffer` 对象被回收，触发图 4 的链条；
3. 然后每次睡 1、2、4、8……毫秒再试，最多睡 9 次（加起来大约半秒）；
4. 还不够，才抛 `OutOfMemoryError`。

第 2 步用的正是 `System.gc()`。加了 `-XX:+DisableExplicitGC`，这次补救就没了。实验：直接内存上限 64MB，每次申请 16MB，用完就不要了，循环 100 次：

```java
for (int i = 1; i <= 100; i++) {
    ByteBuffer buf = ByteBuffer.allocateDirect(16 * 1024 * 1024);   // 16MB，下一轮就没人引用了
    buf.put(0, (byte) 1);
}
System.out.println("100 次全部成功");
```

| 启动参数 | JDK 8 | JDK 21 |
|---|---|---|
| `-Xmx256m`<br>`-XX:MaxDirectMemorySize=64m` | 100 次全部成功 | 100 次全部成功 |
| 再加 `-XX:+DisableExplicitGC` | `OutOfMemoryError: Direct buffer memory` | `OutOfMemoryError: Cannot reserve 16777216 bytes of direct buffer memory (allocated: 67108864, limit: 67108864)` |

第一行能成功，靠的就是第 2 步的 `System.gc()`。打开 GC 日志可以看到：JDK 21 这 100 次申请期间一共发生 24 次 GC，**全部是 `System.gc()` 触发的**，JDK 8 也一样。堆很空，GC 自己根本不会来。第二行把它关掉以后，JDK 21 的报错里写着已分配 67108864 字节，正好是 4 块 16MB，第 5 次申请就失败了。

### 加了这个参数的项目怎么办

- **显式设置 `-XX:MaxDirectMemorySize`**，并且算进容器的内存上限里。
- 如果用的是 CMS 或 G1 这两种垃圾回收器，可以把 `-XX:+DisableExplicitGC` 换成 `-XX:+ExplicitGCInvokesConcurrent`：`System.gc()` 仍然生效，但改走并发回收（GC 的大部分工作和程序同时进行），程序停顿比一次 Full GC 短得多。
- 不指望 GC：像 Netty 那样自己管理直接内存，用完马上释放（见场景 2）。

## 七、实际会碰到它的 5 个场景

业务代码里很少有人直接写 `allocateDirect`，但下面这些场景里，直接内存一直在用。

### 场景 1：你没写 allocateDirect，它也在用

第二节说过：用普通缓冲区读写文件或网络，JDK 会自动用一块临时的直接内存。容易忽略的是后半段：**这块临时内存用完不会马上释放，而是缓存在当前线程里，留着下次用**（`sun.nio.ch.Util` 里每个线程一份缓存），而且默认多大都缓存。

做个实验：用一块普通的 64MB 缓冲区写文件，写完、GC 以后看直接内存用量：

```java
// 一块普通的堆内缓冲区，代码里没有任何 allocateDirect
ByteBuffer heap = ByteBuffer.allocate(64 * 1024 * 1024);
try (FileChannel ch = FileChannel.open(path, StandardOpenOption.WRITE)) {
    while (heap.hasRemaining()) {
        ch.write(heap);
    }
}
heap = null;
System.gc();
// 用 BufferPoolMXBean 读直接内存用量（读法见场景 5）
```

JDK 8 和 JDK 21 的结果一样：写之前直接内存是 0MB，**写完、GC 以后还是 64MB**。这 64MB 被当前线程缓存着，GC 也收不走。加上 `-Djdk.nio.maxCachedBufferSize=1048576`（超过 1MB 的临时内存用完就释放，不缓存）以后，写完是 0MB。

放到线上：一个有 200 个工作线程的服务，如果每个线程偶尔往网络或文件写一次几 MB 的大数据，每个线程就会各自缓存一块几 MB 的直接内存，以后哪怕每次只写几 KB，这块也一直不还。OpenJDK 的问题单 [JDK-8147468](https://bugs.openjdk.org/browse/JDK-8147468) 描述的就是这种情况（一次 4MB 的写，之后都是 8KB），`jdk.nio.maxCachedBufferSize` 这个参数就是为它加的：JDK 9 开始有，JDK 8 从 8u102 开始有。

怎么避免：大块数据分成小块写；或者设上面那个参数；或者自己用一块直接缓冲区反复写。

### 场景 2：Netty，以及底层用 Netty 的框架

Netty 是 Java 里常用的网络通信框架。Netty 4.1 默认用池化的分配器（`io.netty.allocator.type` 默认是 `pooled`），而且默认优先分配直接内存（可以用 `-Dio.netty.noPreferDirect=true` 关掉）。「池化」的意思是：一次向操作系统要一大块，自己切成小块分给各个连接用，用完还回池子里，下次接着用。这正是前面说的「申请一次，反复用」。

很多 RPC 框架的网络通信是用 Netty 实现的（比如 Dubbo 协议默认的通信层就是 Netty），所以即使你没直接写过 Netty 代码，进程里也可能有 Netty 管着的直接内存。

池子里的内存**不靠 GC 释放，靠引用计数**：每个 `ByteBuf`（Netty 自己的缓冲区）记着自己还被几处在用，申请时是 1，每调一次 `release()` 减 1，减到 0 才还回池子。这就绕开了第五、六节的问题：不用等 GC，用完立刻还。代价是必须自己记得释放。Netty 官方给的写法是在 `finally` 里释放：

```java
@Override
public void channelRead(ChannelHandlerContext ctx, Object msg) {
    ByteBuf buf = (ByteBuf) msg;
    try {
        // 处理数据
    } finally {
        buf.release();   // 漏了这一行，这块内存就再也回不到池子里
    }
}
```

<figure class="fig">
<div class="fig-box">
<svg viewBox="0 0 720 256" role="img" aria-label="Netty ByteBuf 正常释放与漏掉释放的对比">
<defs><marker id="dm6-a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah" d="M0 0L10 5L0 10z"/></marker><marker id="dm6-s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="ah-sec" d="M0 0L10 5L0 10z"/></marker></defs>
<text class="t-b" x="20" y="26">正常情况：用完调用 release()</text>
<rect class="bx" x="20" y="40" width="180" height="58" rx="8"/>
<text x="110" y="64" text-anchor="middle">申请 ByteBuf</text>
<text class="t-s" x="110" y="85" text-anchor="middle">计数 = 1</text>
<rect class="bx" x="270" y="40" width="180" height="58" rx="8"/>
<text x="360" y="64" text-anchor="middle">处理数据</text>
<text class="t-s" x="360" y="85" text-anchor="middle">写在 try 里</text>
<rect class="bx" x="520" y="40" width="180" height="58" rx="8"/>
<text x="610" y="64" text-anchor="middle">finally 里 release()</text>
<text class="t-s" x="610" y="85" text-anchor="middle">计数减到 0，还回池子</text>
<path class="ln" d="M200 69H266" marker-end="url(#dm6-a)"/>
<path class="ln" d="M450 69H516" marker-end="url(#dm6-a)"/>
<text class="t-b t-sec" x="20" y="140">美团那次：中途抛了空指针异常</text>
<rect class="bx" x="20" y="154" width="180" height="58" rx="8"/>
<text x="110" y="178" text-anchor="middle">申请 ByteBuf</text>
<text class="t-s" x="110" y="199" text-anchor="middle">计数 = 1</text>
<rect class="bx-off" x="270" y="154" width="180" height="58" rx="8"/>
<text x="360" y="178" text-anchor="middle">编码时抛异常</text>
<text class="t-s" x="360" y="199" text-anchor="middle">subType 字段是 null</text>
<rect class="bx-off" x="520" y="154" width="180" height="58" rx="8"/>
<text x="610" y="178" text-anchor="middle">释放的代码没执行</text>
<text class="t-s" x="610" y="199" text-anchor="middle">计数一直是 1</text>
<path class="ln" d="M200 183H266" marker-end="url(#dm6-a)"/>
<path class="ln ln-sec ln-dash" d="M450 183H516" marker-end="url(#dm6-s)"/>
<text class="t-s" x="20" y="244">每断开一个连接漏 256 字节。池子里的内存不归 GC 管，只能一直积累到上限</text>
</svg>
</div>
<figcaption>图 6　Netty 的内存靠引用计数归还，漏调一次 release()，GC 也帮不上忙</figcaption>
</figure>

美团技术团队的排查记录[《Netty 堆外内存泄露排查盛宴》](https://tech.meituan.com/2018/10/18/netty-direct-memory-screening.html)（2018）就是这种情况：他们的长连接服务在处理「客户端断开」时先申请了一块内存，接着因为一个字段是 null 抛了空指针异常，后面释放内存的代码没执行到。每断开一个连接漏 256 字节，一直积累到上限，最后报内存溢出。他们是用反射读 Netty 内部的计数器 `DIRECT_MEMORY_COUNTER`、每秒打印一次，才看到直接内存在慢慢上涨。

排查这类问题，Netty 自带泄漏检测：默认级别是 `SIMPLE`，抽 1% 的 `ByteBuf` 检查，只告诉你有没有泄漏；改成 `-Dio.netty.leakDetection.level=advanced`，还会告诉你泄漏的那块最后在哪些地方被用过。日志里搜 `LEAK:`。

### 场景 3：只转发、不改内容的网络程序

网关、代理这类程序，数据从一个连接读进来，原样写到另一个连接，Java 代码基本不看内容。这正是直接缓冲区最合适的地方：用普通缓冲区的话，读进来要多复制一次，写出去又要多复制一次（图 2）；用直接缓冲区，这两次都省了。

```java
ByteBuffer buf = ByteBuffer.allocateDirect(64 * 1024);  // 每个连接一块，64KB，只申请一次
while (from.read(buf) != -1) {        // from、to 都是 SocketChannel（NIO 里的网络连接）
    buf.flip();
    while (buf.hasRemaining()) {
        to.write(buf);
    }
    buf.clear();                      // 清空，下一轮接着用同一块
}
```

要点只有一个：**这块缓冲区只申请一次，反复用。** 如果每读一次都 `allocateDirect` 一块，申请和释放的开销会抵消省下的复制，还可能出现第五节说的「已经不用了，迟迟不释放」。

如果数据要在 Java 里逐个字节地解析、计算，直接缓冲区就省不了什么，用普通缓冲区更简单。

### 场景 4：本地缓存放不下了，放到堆外

本地缓存要放几个 GB 数据时，全放堆里会让 GC 负担很重：这些对象要被 GC 反复检查，整理内存时还要搬动它们（图 1）。Ehcache 3（一个常用的 Java 本地缓存库）提供「堆外层」，可以把缓存数据放进直接内存：

```java
CacheConfigurationBuilder.newCacheConfigurationBuilder(Long.class, String.class,
    ResourcePoolsBuilder.newResourcePoolsBuilder()
        .heap(10, EntryUnit.ENTRIES)      // 堆里最多 10 条，访问最快
        .offheap(10, MemoryUnit.MB))      // 堆外最多 10MB，容量更大
    .build();
```

Ehcache 的文档提醒了两点：放堆外的数据要序列化（把对象转成字节）和反序列化，所以比放在堆里慢，适合「数据量大、放堆里会严重影响 GC」的情况；另外要按打算使用的堆外大小设 `-XX:MaxDirectMemorySize`。

### 场景 5：线上排查：进程内存比堆大很多

这可能是最常碰到的场景：容器里的 Java 服务被系统杀掉了（Kubernetes 里显示 `OOMKilled`，意思是内存超了容器上限被强制结束），但 GC 日志正常，堆也没满；或者 `top` 里看到进程占的内存（`RES` 那一列）比 `-Xmx` 大出一大截。

常见原因是只按堆算了内存：`-Xmx` 设得和容器上限差不多，没给直接内存、元空间、线程栈留出地方（图 3）。排查顺序：

**1. 先看是不是直接内存。** JDK 自己有统计，代码里能直接读：

```java
for (BufferPoolMXBean pool : ManagementFactory.getPlatformMXBeans(BufferPoolMXBean.class)) {
    // name 为 direct 的是直接内存；mapped 是内存映射文件
    System.out.println(pool.getName() + " 已用 " + pool.getMemoryUsed() / 1024 / 1024 + " MB");
}
```

用 Spring Boot 的话不用自己写：Micrometer 的 `jvm.buffer.memory.used` 指标（标签 `id=direct`）读的就是它。注意，它只统计通过 `allocateDirect` 申请的部分，第五节用 `Unsafe` 直接申请的内存它看不到。

**2. 再用 NMT 看堆外的全貌。** NMT（Native Memory Tracking）是 JVM 自带的堆外内存统计，能分类看到 JVM 自己申请的各种堆外内存（包括用 `Unsafe` 申请的；第三方本地库在 C 代码里自己申请的看不到）。启动时加 `-XX:NativeMemoryTracking=summary`，运行时执行：

```bash
jcmd <pid> VM.native_memory summary scale=MB
```

直接内存在 JDK 8 里算在 `Internal` 一项，JDK 21 里算在 `Other` 一项。比如申请 200MB 直接内存后，JDK 8 的 `Internal` 一项是 211MB，JDK 21 的 `Other` 一项是 200MB。NMT 本身有一些额外开销，一般排查时才打开。

**3. 用了 Netty 的，打开泄漏检测**（场景 2）。

## 八、什么时候不该用

- **小的、用一下就扔的缓冲区**：申请和释放比普通缓冲区贵，用普通的。
- **数据主要在 Java 里计算，不怎么交给操作系统读写**：省不掉什么复制。
- **拿不准的时候**：按 JDK 文档的建议，只有能测出性能提升才用。

## 九、总结

1. **是什么、为什么快**：直接内存是堆外的一块内存，Java 代码和操作系统都能直接访问。堆里的对象会被 GC 挪动，所以普通缓冲区读写时，JDK 要先经过一块临时的堆外内存再复制一次；直接缓冲区本来就在堆外，省掉了这次复制。
2. **会溢出**：上限是 `-XX:MaxDirectMemorySize`，不设约等于 `-Xmx`；超了报 `OutOfMemoryError: Direct buffer memory`。
3. **怎么释放**：`allocateDirect` 用 `Unsafe` 申请内存，同时登记一个 `Cleaner`。堆里的 `DirectByteBuffer` 对象被 GC 回收后，`Cleaner` 收到通知，Reference Handler 线程执行释放任务，调用 `freeMemory`。所以释放时间取决于 GC 什么时候来。
4. **和 `-XX:+DisableExplicitGC` 的冲突**：JDK 在额度不够时会调 `System.gc()` 来触发释放，这个参数让它失效，直接内存就更容易溢出。
5. **在哪用到**：用普通缓冲区做 NIO 读写时 JDK 自动用；Netty 和基于它的框架；网关、代理这类只转发的程序；堆外缓存；线上排查进程内存问题时也要看它。

### 面试怎么答

> 直接内存是堆外的一块内存，用 `ByteBuffer.allocateDirect` 申请，Java 代码和操作系统都能直接访问。它主要用在读写文件和网络：堆里的对象会被 GC 挪动，所以用普通缓冲区读写时，JDK 要先复制到一块临时的堆外内存再交给操作系统；直接用直接内存就省掉这次复制。代价是申请和释放比堆内存慢，所以一般申请一次反复用，Netty 的内存池就是这么做的。
>
> 它的上限是 `-XX:MaxDirectMemorySize`，不设就约等于最大堆。释放靠 `Cleaner`：堆里的 `DirectByteBuffer` 对象被 GC 回收后，Reference Handler 线程执行释放任务，调用 `Unsafe.freeMemory`。所以堆很空、一直不 GC 时，直接内存可能迟迟不释放。JDK 申请时额度不够会主动调一次 `System.gc()`，如果线上加了 `-XX:+DisableExplicitGC`，这次补救就失效了。排查用 `BufferPoolMXBean` 和 NMT。

## 参考

- 美团技术团队：[Netty 堆外内存泄露排查盛宴](https://tech.meituan.com/2018/10/18/netty-direct-memory-screening.html)
- 黑马程序员：[JVM 完整教程，第 41–47 集（直接内存）](https://www.bilibili.com/video/BV1yE411Z7AP?p=41)
