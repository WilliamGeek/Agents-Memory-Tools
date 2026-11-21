# binaries

把构建好的 Python sidecar 放在这里，文件名必须是 Tauri 要求的 target-triple 形式：

```
memory-tools-x86_64-pc-windows-msvc.exe
```

`tauri.conf.json` 中的 `externalBin: ["binaries/memory-tools"]` 会自动补上 target triple。
不要提交真实 exe 或用户数据到 Git；本目录只保留说明和 `.gitkeep`。
