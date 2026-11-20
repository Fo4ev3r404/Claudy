#include <windows.h>
#include <shobjidl.h>
#include <string>

// Native C++ Application Host for Claudy 1.7 // Rob Run AI v7
// Supports both Portable Mode (_internal\python314.dll for PCs without Python installed)
// and Local Mode (C:\Python314\python314.dll), completely eliminating the PyInstaller bootloader.

typedef int (*Py_Main_t)(int argc, wchar_t **argv);

static bool FileExistsW(const std::wstring& path) {
    DWORD attr = GetFileAttributesW(path.c_str());
    return (attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY));
}

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow) {
    HMODULE hShell32 = LoadLibraryW(L"shell32.dll");
    if (hShell32) {
        typedef HRESULT (WINAPI *SetAppID_t)(PCWSTR);
        SetAppID_t pSetAppID = (SetAppID_t)GetProcAddress(hShell32, "SetCurrentProcessExplicitAppUserModelID");
        if (pSetAppID) {
            pSetAppID(L"Claudy.RobRun.AI.v7");
        }
    }

    wchar_t exePath[MAX_PATH];
    GetModuleFileNameW(NULL, exePath, MAX_PATH);
    std::wstring dir(exePath);
    size_t pos = dir.find_last_of(L"\\/");
    if (pos != std::wstring::npos) {
        dir = dir.substr(0, pos);
    }
    SetCurrentDirectoryW(dir.c_str());

    std::wstring portableInternal = dir + L"\\_internal";
    std::wstring portablePyDll = portableInternal + L"\\python314.dll";
    HMODULE hPy = NULL;

    if (FileExistsW(portablePyDll)) {
        // Portable mode: works on any PC without Python installed!
        std::wstring pyPath = portableInternal + L"\\base_library.zip;" + portableInternal;
        SetEnvironmentVariableW(L"PYTHONHOME", portableInternal.c_str());
        SetEnvironmentVariableW(L"PYTHONPATH", pyPath.c_str());
        SetEnvironmentVariableW(L"PYTHONNOUSERSITE", L"1");
        SetDllDirectoryW(portableInternal.c_str());
        hPy = LoadLibraryExW(portablePyDll.c_str(), NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    } else {
        // Local development mode
        SetDllDirectoryW(L"C:\\Python314");
        hPy = LoadLibraryExW(L"C:\\Python314\\python314.dll", NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
        if (!hPy) {
            hPy = LoadLibraryW(L"python314.dll");
        }
    }

    if (hPy) {
        Py_Main_t pPyMain = (Py_Main_t)GetProcAddress(hPy, "Py_Main");
        if (pPyMain) {
            std::wstring cmdLineStr(GetCommandLineW());
            std::wstring scriptDir = FileExistsW(dir + L"\\rob_run_loader.py") ? dir : portableInternal;
            std::wstring targetScript = scriptDir + L"\\rob_run_loader.py";
            if (cmdLineStr.find(L"--overlay") != std::wstring::npos) {
                targetScript = scriptDir + L"\\live_overlay.py";
            }

            wchar_t* pyArgv[3];
            pyArgv[0] = exePath;
            pyArgv[1] = (wchar_t*)targetScript.c_str();
            pyArgv[2] = NULL;
            return pPyMain(2, pyArgv);
        }
    }

    MessageBoxW(NULL, L"Could not load Python runtime library.", L"Claudy 1.7", MB_ICONERROR);
    return 1;
}
