# PKGLens 🔍

A comprehensive package management dashboard that provides a unified view of your installed packages across multiple package managers including pip, Homebrew, and npm.

![PKGLens Dashboard](https://img.shields.io/badge/Status-Active-brightgreen)
![Python](https://img.shields.io/badge/Python-3.7+-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## ✨ Features

### 📦 Package Management
- **Multi-manager Support**: View packages from pip, pip3, Homebrew, and global npm installations
- **Comprehensive Details**: Package names, versions, sizes, paths, and installation sources
- **Search & Filter**: Powerful search functionality across all package attributes
- **Export Capabilities**: Export package data to CSV format

### ✅ Package Verification
- **Integrity Checks**: Verify package integrity and importability
- **Status Tracking**: Persistent verification status that survives page refreshes
- **Batch Verification**: Verify all packages at once with progress tracking
- **Security Audits**: Integration with pip-audit for vulnerability detection

### ⚠️ Conflict Detection
- **Dependency Conflicts**: Identify package conflicts and compatibility issues
- **Severity Levels**: Categorized conflicts by severity (high, medium, low)
- **Actionable Suggestions**: Get recommendations for resolving conflicts

### 📊 History & Analytics
- **Uninstall History**: Track packages that have been removed
- **Missing Package Detection**: Identify packages uninstalled outside the dashboard
- **Size Analytics**: Total size calculations and package size breakdowns

### 🎨 Modern UI
- **Dark Theme**: Beautiful dark mode interface
- **Responsive Design**: Works on desktop and mobile devices
- **Real-time Updates**: Live data updates without page refresh
- **Tabbed Interface**: Organized sections for different functionalities

## 🚀 Quick Start

### Prerequisites
- Python 3.7 or higher
- Package managers: pip, Homebrew (macOS), npm (optional)

### Installation

1. **Clone or download the project**
   ```bash
   git clone <repository-url>
   cd <repository>
   ```

2. **Run PKGLens**
   ```bash
   python3 pkglens.py --open
   ```

   This will:
   - Collect package information from all supported managers
   - Generate the dashboard HTML
   - Start a local web server
   - Open the dashboard in your default browser

### Usage Options

```bash
# Basic usage - generate dashboard and print path
python3 pkglens.py

# Open dashboard in browser automatically
python3 pkglens.py --open

# Use a specific port
python3 pkglens.py --port 8080

# Use a random available port
python3 pkglens.py --port 0
```

## 📋 Dashboard Sections

### 📦 Installed Packages
- **Overview**: Complete list of all installed packages
- **Search**: Filter by name, version, source, or path
- **Manager Filter**: Filter by package manager (pip, brew, npm)
- **Actions**: Uninstall packages directly from the dashboard
- **Verification**: Quick verify buttons with status indicators

### ✅ Verification Status
- **Status Overview**: View verification status for all packages
- **Filter by Status**: Filter by verified, failed, unknown, or unverified
- **Batch Operations**: Verify all packages at once
- **Detailed Messages**: See specific verification results and error messages

### ⚠️ Conflicts & Issues
- **Conflict Detection**: Automated scanning for package conflicts
- **Severity Assessment**: High, medium, and low priority issues
- **Resolution Guidance**: Suggestions for fixing conflicts
- **Package Details**: Affected packages and their versions

### 🗑️ Uninstall History
- **Historical Data**: Track all uninstalled packages
- **Source Tracking**: Distinguish between dashboard and external uninstalls
- **Missing Detection**: Find packages removed outside the dashboard
- **Data Export**: Export history for analysis

## 🔧 Technical Details

### Supported Package Managers

| Manager | Description | Verification Method |
|---------|-------------|-------------------|
| **pip** | Python packages in current environment | Import test + pip-audit |
| **Homebrew** | macOS package manager | brew audit |
| **npm (global)** | Global Node.js packages | npm audit |

```


## 🛠️ Development

### Adding New Package Managers

To add support for a new package manager:

1. **Implement collection function** in `collect_all()`
2. **Add verification logic** in `verify_package_integrity()`
3. **Update UI filters** in the dashboard
4. **Test integration** with existing functionality

### Customization

- **Styling**: Modify CSS variables in the HTML file
- **Features**: Extend JavaScript functions for new functionality
- **Data Sources**: Add new data collection methods
- **Verification**: Implement custom verification logic

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with Python's standard library for maximum compatibility
- Uses modern web technologies for responsive UI
- Integrates with existing package managers without modification
- Inspired by the need for unified package management across different ecosystems
