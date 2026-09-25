// School ERP - Silent Windows Launcher
// Launches run_server.py via pythonw.exe (no console, no flash).
// Build: go build -ldflags="-H windowsgui -s -w" -o SchoolERP.exe .
package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"unsafe"
)

var (
	moduser32       = syscall.NewLazyDLL("user32.dll")
	procMessageBoxW = moduser32.NewProc("MessageBoxW")
)

func showError(msg string) {
	title, _ := syscall.UTF16PtrFromString("School ERP")
	text, _ := syscall.UTF16PtrFromString(msg)
	procMessageBoxW.Call(0,
		uintptr(unsafe.Pointer(text)),
		uintptr(unsafe.Pointer(title)),
		0x10, // MB_ICONERROR
	)
}

func main() {
	// Resolve install directory from this exe's location
	exePath, err := os.Executable()
	if err != nil {
		showError("Cannot locate executable:\n" + err.Error())
		return
	}
	installDir := filepath.Dir(exePath)

	// Prefer pythonw.exe (truly windowless); fall back to python.exe
	pythonw := filepath.Join(installDir, "venv", "Scripts", "pythonw.exe")
	if _, err := os.Stat(pythonw); err != nil {
		pythonw = filepath.Join(installDir, "venv", "Scripts", "python.exe")
		if _, err2 := os.Stat(pythonw); err2 != nil {
			showError("Python virtual environment not found.\n\nExpected:\n" +
				filepath.Join(installDir, "venv", "Scripts", "pythonw.exe") +
				"\n\nPlease run setup.bat first.")
			return
		}
	}

	// Accept run_server.py or obfuscated run_server.pyc
	runServer := filepath.Join(installDir, "run_server.py")
	if _, err := os.Stat(runServer); err != nil {
		runServer = filepath.Join(installDir, "run_server.pyc")
		if _, err2 := os.Stat(runServer); err2 != nil {
			showError("run_server.py not found in:\n" + installDir +
				"\n\nPlease re-run setup.bat.")
			return
		}
	}

	// Launch — fully detached, no console window whatsoever
	cmd := exec.Command(pythonw, runServer)
	cmd.Dir = installDir
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: 0x08000000 | // CREATE_NO_WINDOW
			0x00000008, // DETACHED_PROCESS
	}

	if err := cmd.Start(); err != nil {
		showError("Failed to launch School ERP:\n" + err.Error())
	}
}
