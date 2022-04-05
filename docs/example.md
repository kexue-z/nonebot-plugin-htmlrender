md2pic <div align="center">
<h1>html格式支持和居中</h1>
<img width="250" src="https://v2.nonebot.dev/logo.png"/>
<div>
html格式 图片支持
</div> 
</div> 

# 一级标题
## 二级标题
### 三级标题
#### 四级标题
##### 五级标题
###### 六级标题

# 文本
*斜体文本*

_斜体文本_

**粗体文本**

__粗体文本__

***粗斜体文本***

___粗斜体文本___

<s>删除线</s>

~~删除线~~

<u>下划线</u>

~小号~字体

emoji 😀😃😄😁😆😅

列表

* 第一项
* 第二项
* 第三项

1. 第一项
2. 第二项
3. 第三项

任务列表

- [X] 第一项
- [ ] 第二项

# 嵌套
1. 第一项：
    - 第一项嵌套的第一个元素
    - 第一项嵌套的第二个元素
2. 第二项：
    - 第二项嵌套的第一个元素
    - 第二项嵌套的第二个元素

- [X] 任务 1
    * [X] 任务 A
    * [ ] 任务 B
        + [x] 任务 a
        + [ ] 任务 b
        + [x] 任务 c
    * [X] 任务 C
- [ ] 任务 2
- [ ] 任务 3

分割线
----

# 图片

- 必须指定宽度或大小 如 `250` 或 `100%`
```html
<img width="20%" src="https://v2.nonebot.dev/logo.png"/>
```

# html同款标签

如 <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Del</kbd>

# 引用

> 最外层
> > 第一层嵌套
> > > 第二层嵌套

# 代码

```python
import this
```
行内代码 `print("nonebot")`

# 表格
| 左对齐 | 右对齐 | 居中对齐 |
| :-----| ----: | :----: |
| 单元格 | 单元格 | 单元格 |
| 单元格 | 单元格 | 单元格 |

# 数学公式

单行公式

$$(1+x)^\alpha =1+\alpha x +\frac{\alpha (\alpha -1}{2!} x^2+\cdots+\frac{\alpha (\alpha - 1)\cdots(\alpha - n+1)}{n!}x^n+o(x^n)$$

`$$...$$`

行内公式 $f'(x_0)=\lim_{x\rightarrow x_0} \frac{f(x)-f(x_0)}{\Delta x}$ 行内公式

`$...$`

# 不支持
- md 格式图片插入（必须使用html格式）
- 某些符号会被自动转换