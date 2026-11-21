"""Entry point for the frozen (PyInstaller) application.

Without arguments (or with file paths) the GUI starts; ``analyze …`` or
``--version`` run the command line interface.
"""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] in ("analyze", "--version", "-h", "--help"):
        from frameforge.cli import main as cli_main

        sys.exit(cli_main(sys.argv[1:]))
    from frameforge.gui.app import main

    sys.exit(main())
