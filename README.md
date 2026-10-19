# Kindle Auto Prepare

Calibre 文件类型插件：在导入 EPUB，以及从 EPUB 转换格式前，自动处理译注显示、目录目标和封面引用。

## 功能

- **段后译注**：将结构明确、仅被引用一次的脚注移到引用所在段落后，以普通正文显示，避免 Kindle 将其识别为弹窗注释。
- **注释加深**：加深译注和 ruby 注音文字；保留插图中明确指定的白色注音。
- **目录定位**：为可确认的文件级目录目标补上标题锚点，同步 NCX、EPUB 3 导航和对应链接。
- **封面引用**：补全可确认的封面图片元数据和封面页引用，保留原图。
- **保留源文件**：Calibre 使用处理后的临时副本，导入前的原始 EPUB 不变。重复处理不会重复插入注释或锚点。

## 安装

1. 从 [Releases](https://github.com/kiyasu-desu/calibre-kindle-auto-prepare/releases) 下载 `KindleAutoPrepare-版本号.zip`。
2. 在 Calibre 中打开「首选项 → 插件 → 从文件加载插件」，选择下载的 ZIP。
3. 重启 Calibre。
4. 在「文件类型」分类找到 **Kindle Auto Prepare**，点击「自定义插件」调整各项开关。

要求 Calibre 7.0 或更新版本。已在 Windows 的 Calibre 9.16.0 验证；macOS 和 Linux 的 Calibre 界面尚未实机验证。

## 发送到 Kindle

建议将输出格式设为 **AZW3**，从 EPUB 转换后，通过 Calibre 的「发送到设备」使用 USB 传入 Kindle。

插件处理 EPUB 的内部结构；Kindle 书架缩略图的生成、上传和恢复由 Calibre 内置 Kindle 驱动负责。插件不会生成缺失的封面图，也不会单独修复 Kindle 设备上的缓存。

已在书库中的 EPUB 会在下一次转换时处理。直接发送已有的 MOBI/AZW3 不会触发 EPUB 处理，应从 EPUB 重新转换。插件不会自动批量改写已有书库，也不会修改书籍 UUID 或阅读记录。已经导入过的旧版本若受到设备缓存影响，仍可能需要重新导入。

## 处理边界

- 只处理可解析的 EPUB，不处理 PDF，也不将 MOBI/AZW3 还原为 EPUB。
- 共享脚注、嵌套脚注、被其他链接引用的注释内部结构，以及无法确认的目录目标保留原样，并记录警告。
- 不猜测损坏的目录片段位置；缺少封面图时不随意选择正文插图。
- 处理异常时，Calibre 导入/转换流程使用原始文件继续。
- 报告位于 Calibre 配置目录下的 `plugins/kindle_auto_prepare_reports/`。可通过「首选项 → 杂项 → 打开 Calibre 配置目录」找到。

## 命令行

安装插件后，可单独处理一份 EPUB：

```text
calibre-debug -r "Kindle Auto Prepare" -- input.epub output.epub
calibre-debug -r "Kindle Auto Prepare" -- input.epub output.epub --no-inline-notes
```

命令不会覆盖输入文件；当报告中的 `changed` 为 `false` 时，不生成新的输出文件，可继续使用输入文件。命令行默认启用各项处理，不读取 Calibre 界面的开关；`--no-inline-notes` 可保留原脚注形式。

## 开发

```text
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python scripts/build_plugin.py
```

构建产物为 `dist/KindleAutoPrepare-1.0.0.zip`，可直接安装到 Calibre。构建脚本使用文件白名单，同一环境、相同输入生成一致的 ZIP；书籍、日志、本机配置和测试数据不会进入安装包。

```text
plugin/                    Calibre 插件源码和导入标记
tests/                     自动生成合成 EPUB 的行为测试、安装包测试
scripts/build_plugin.py    安装包构建脚本
.github/workflows/test.yml  Windows / Linux 自动测试
```

Python 测试依赖 lxml；Calibre 运行时使用自身提供的 Python、Qt 和 lxml，无需另行安装依赖。

## 验证范围

行为测试覆盖段后译注、跨文件图片、共享/嵌套注释保护、目录精确锚点、封面绑定、源文件保护、重复处理和打包白名单。另已用本地书籍验证 Calibre 导入钩子、EPUB → AZW3 转换和段后译注结构，Kindle 实机反馈确认了封面和目录修复效果。真实书籍、个人配置和设备文件不随仓库发布。
