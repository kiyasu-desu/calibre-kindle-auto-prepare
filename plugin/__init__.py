from calibre.customize import FileTypePlugin


class KindleAutoPrepare(FileTypePlugin):
    name = "Kindle Auto Prepare"
    description = "自动处理 EPUB 译注、目录和封面引用；保留导入前的源文件。"
    supported_platforms = ["windows", "osx", "linux"]
    author = "kiyasu-desu"
    version = (1, 0, 0)
    minimum_calibre_version = (7, 0, 0)
    file_types = {"epub"}
    on_import = True
    on_preprocess = True
    priority = 0

    def run(self, path_to_ebook):
        from calibre_plugins.kindle_auto_prepare.core import prepare_epub
        from calibre_plugins.kindle_auto_prepare.config import prefs
        import json
        import os
        import traceback

        options = {name: prefs[name] for name in prefs.defaults}
        if not options["enabled"]:
            return path_to_ebook
        temporary = self.temporary_file(".epub")
        temporary.close()
        try:
            report = prepare_epub(path_to_ebook, temporary.name, options)
            from calibre.constants import config_dir
            report_dir = os.path.join(config_dir, "plugins", "kindle_auto_prepare_reports")
            os.makedirs(report_dir, exist_ok=True)
            filename = report.get("source_sha256", "last")[:24] + ".json"
            with open(os.path.join(report_dir, filename), "w", encoding="utf-8") as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2)
            print("[Kindle Auto Prepare] " + json.dumps(report, ensure_ascii=True))
            return temporary.name if report["changed"] else path_to_ebook
        except Exception:
            print("[Kindle Auto Prepare] Processing skipped; the input file is unchanged.")
            traceback.print_exc()
            return path_to_ebook

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.kindle_auto_prepare.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()

    def cli_main(self, args):
        import argparse
        import json
        from calibre_plugins.kindle_auto_prepare.core import prepare_epub
        parser = argparse.ArgumentParser(description="Prepare an EPUB without changing the source.")
        parser.add_argument("source")
        parser.add_argument("destination")
        parser.add_argument("--no-inline-notes", action="store_true")
        options = parser.parse_args(args[1:])
        report = prepare_epub(options.source, options.destination,
                              {"inline_notes": not options.no_inline_notes})
        print(json.dumps(report, ensure_ascii=False, indent=2))
