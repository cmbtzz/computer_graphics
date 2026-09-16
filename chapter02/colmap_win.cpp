#include <iostream>
#include <string>
#include <vector>
#include <cstring>
#include <windows.h>
// ========== Fixed Configuration ==========
const std::string COLMAP_EXE = R"(E:\download\COLMAP-3.6-windows-cuda\bin\colmap.exe)";
const std::string IMAGE_FOLDER = R"(images\Tanks_and_Temples\Horse)";
const std::string WORKSPACE_FOLDER = R"(output)";
// =========================================

// Switch working directory to source folder
bool setWorkDirToSourceFolder()
{
    char exePathBuf[MAX_PATH] = { 0 };
    GetModuleFileNameA(NULL, exePathBuf, MAX_PATH);
    std::string exeFullPath(exePathBuf);
    size_t lastSlashPos = exeFullPath.find_last_of("\\");
    std::string exeDir = exeFullPath.substr(0, lastSlashPos);
    std::string sourceFolder = R"(D:\WorkspaceC\ComputerGraphics_2025\chapter02-2026)";
    BOOL ret = SetCurrentDirectoryA(sourceFolder.c_str());
    if (!ret)
    {
        std::cerr << "SetCurrentDirectory failed, cannot switch to source folder: " << sourceFolder << "\n";
        return false;
    }
    std::cout << "Working directory switched to: " << sourceFolder << "\n";
    return true;
}

// Check if path exists (Windows API)
bool pathExists(const std::string& path)
{
    DWORD attr = GetFileAttributesA(path.c_str());
    return attr != INVALID_FILE_ATTRIBUTES;
}

// Recursively create directories, replacement for fs::create_directories
bool createDirectories(const std::string& path)
{
    size_t pos = 0;
    std::string dir;
    while ((pos = path.find("\\", pos)) != std::string::npos)
    {
        dir = path.substr(0, pos);
        if (!pathExists(dir))
        {
            if (!CreateDirectoryA(dir.c_str(), nullptr))
            {
                DWORD err = GetLastError();
                if (err != ERROR_ALREADY_EXISTS)
                {
                    std::cerr << "Failed to create directory: " << dir << " err=" << err << "\n";
                    return false;
                }
            }
        }
        pos++;
    }
    // Create final directory
    if (!CreateDirectoryA(path.c_str(), nullptr))
    {
        DWORD err = GetLastError();
        if (err != ERROR_ALREADY_EXISTS)
        {
            std::cerr << "Failed to create final directory: " << path << " err=" << err << "\n";
            return false;
        }
    }
    return true;
}

// Launch COLMAP command via CreateProcessA
int runColmapCmd(const std::vector<std::string>& args, const std::string& desc)
{
    std::cout << "\n==== " << desc << " ====\n";
    std::string cmdLine = "\"" + COLMAP_EXE + "\"";
    for (const auto& arg : args)
    {
        cmdLine += " " + arg;
    }
    // std::cout << "Executing command: " << cmdLine << "\n";

    std::vector<char> cmdBuf(cmdLine.size() + 1, 0);
    memcpy(cmdBuf.data(), cmdLine.c_str(), cmdLine.size());

    STARTUPINFOA si{};
    PROCESS_INFORMATION pi{};
    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);

    BOOL ok = CreateProcessA(
        nullptr,
        cmdBuf.data(),
        nullptr,
        nullptr,
        FALSE,
        0,
        nullptr,
        nullptr,
        &si,
        &pi
    );

    if (!ok)
    {
        DWORD err = GetLastError();
        std::cerr << "CreateProcessA failed, error code = " << err << "\n";
        return -1;
    }

    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD exitCode = 0;
    GetExitCodeProcess(pi.hProcess, &exitCode);
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);

    if (exitCode != 0)
    {
        std::cerr << "Command failed, exit code: " << exitCode << "\n";
    }
    return static_cast<int>(exitCode);
}

// Full COLMAP reconstruction pipeline
int runColmapPipeline()
{
    createDirectories(WORKSPACE_FOLDER);

    std::string dbPath = WORKSPACE_FOLDER + "\\database.db";
    std::string sparsePath = WORKSPACE_FOLDER + "\\sparse";
    std::string densePath = WORKSPACE_FOLDER + "\\dense";

    createDirectories(sparsePath);
    createDirectories(densePath);

    // Step1 SIFT feature extraction
    int ret = runColmapCmd({
        "feature_extractor",
        "--database_path", dbPath,
        "--image_path", IMAGE_FOLDER
    }, "step 1. SIFT Feature Extraction (feature_extractor)");
    if (ret != 0) return ret;

    // Step2 Sequential matching
    ret = runColmapCmd({
        "sequential_matcher",
        "--database_path", dbPath
    }, "Step 2. Sequential Feature Matching (sequential_matcher)");
    if (ret != 0) return ret;

    // Step3 Incremental SfM sparse reconstruction
    ret = runColmapCmd({
        "mapper",
        "--database_path", dbPath,
        "--image_path", IMAGE_FOLDER,
        "--output_path", sparsePath
    }, "Step 3. Incremental SfM Sparse Reconstruction (mapper)");
    if (ret != 0) return ret;

    // Step4 Image undistortion
    ret = runColmapCmd({
        "image_undistorter",
        "--image_path", IMAGE_FOLDER,
        "--input_path", sparsePath + "\\0",
        "--output_path", densePath
    }, "Step 4. Image Undistortion (image_undistorter)");
    if (ret != 0) return ret;

    // Step5 PatchMatch Stereo MVS dense reconstruction
    // ret = runColmapCmd({
    //     "patch_match_stereo",
    //     "--workspace_path", densePath,
    //     "--workspace_format", "COLMAP"
    // }, "5. PatchMatch Stereo MVS (patch_match_stereo)");

    ret = runColmapCmd({
        "patch_match_stereo",
        "--workspace_path", densePath,
        "--workspace_format", "COLMAP",
        "--PatchMatchStereo.max_image_size", "1000",
        "--PatchMatchStereo.window_radius", "4",
        "--PatchMatchStereo.window_step", "2",
        "--PatchMatchStereo.num_iterations", "2",
        "--PatchMatchStereo.filter_min_num_consistent", "2",
        "--PatchMatchStereo.filter_geom_consistency_max_cost", "1",
        "--PatchMatchStereo.write_consistency_graph", "0",
        "--PatchMatchStereo.geom_consistency", "false"
    }, "Step 5. PatchMatch Stereo MVS (patch_match_stereo)");
    if (ret != 0) return ret;

    // Step6 Fuse depth maps to dense point cloud fused.ply
    ret = runColmapCmd({
        "stereo_fusion",
        "--workspace_path", densePath,
        "--input_type", "photometric",
        "--output_path", densePath + "\\fused.ply"
    }, "step 6. Depth Map Fusion, output dense PLY point cloud");
    if (ret != 0) return ret;

    std::cout << "\n======== COLMAP Pipeline Completed ========\n";
    std::cout << "Dense point cloud output: " << densePath << "\\fused.ply\n";
    return 0;
}

int main()
{
    SetConsoleOutputCP(65001);
    std::cout << "==== COLMAP Reconstruction Pipeline Started ====\n";

    if (!setWorkDirToSourceFolder())
    {
        system("pause");
        return -1;
    }

    if (!pathExists(COLMAP_EXE))
    {
        std::cerr << "Cannot find colmap.exe: " << COLMAP_EXE << "\n";
        system("pause");
        return -1;
    }

    if (!pathExists(IMAGE_FOLDER))
    {
        std::cerr << "Image folder does not exist: " << IMAGE_FOLDER << "\n";
        system("pause");
        return -1;
    }

    std::cout << "All pre-checks passed\n";
    int result = runColmapPipeline();

    if(result == 0)
    {
        std::cout << "\nAll tasks finished successfully!\n";
    }
    else
    {
        std::cerr << "\nPipeline execution failed!\n";
    }

    system("pause");
    return result;
}