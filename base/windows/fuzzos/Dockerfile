# escape=`
ARG core=mcr.microsoft.com/windows/servercore:1809
ARG target=mcr.microsoft.com/windows/nanoserver:1809
FROM $core as download

LABEL maintainer Christoph Diehl cdiehl@mozilla.com

SHELL ["powershell", "-ExecutionPolicy", "Bypass", "-Command", "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue';"]


ENV PS_VERSION 6.1.2 `
    PS_DOWNLOAD_URL https://github.com/PowerShell/PowerShell/releases/download/v${PS_VERSION}/PowerShell-${PS_VERSION}-win-x64.zip
RUN [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; `
    Invoke-WebRequest -UseBasicParsing $env:PS_DOWNLOAD_URL -OutFile powershell.zip; `
    Expand-Archive powershell.zip -DestinationPath \PowerShell; `
    Remove-Item powershell.zip -Force;


ENV RG_VERSION 0.10.0 `
    RG_DOWNLOAD_URL https://github.com/BurntSushi/ripgrep/releases/download/${RG_VERSION}/ripgrep-${RG_VERSION}-x86_64-pc-windows-msvc.zip
RUN [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; `
    Invoke-WebRequest -UseBasicParsing $env:RG_DOWNLOAD_URL -OutFile ripgrep.zip; `
    Expand-Archive ripgrep.zip -DestinationPath \ripgrep ; `
    Remove-Item ripgrep.zip -Force;


ENV ZIP_VERSION 1806 `
    ZIP_DOWNLOAD_URL https://www.7-zip.org/a/7z${ZIP_VERSION}-x64.exe
RUN Invoke-WebRequest -UseBasicParsing $env:ZIP_DOWNLOAD_URL -OutFile 7zip.exe; `
    Start-Process `
        -FilePath 'C:\7zip.exe' `
        -ArgumentList '/S' `
        -NoNewWindow `
        -Wait `
        -Verbose; `
    [Environment]::SetEnvironmentVariable('PATH', $env:Path + ';C:\Program Files\7-Zip', [EnvironmentVariableTarget]::Machine); `
    Remove-Item 7zip.exe -Force;


ENV MICRO_VERSION 1.4.1 `
    MICRO_DOWNLOAD_URL https://github.com/zyedidia/micro/releases/download/v${MICRO_VERSION}/micro-${MICRO_VERSION}-win64.zip
RUN [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; `
    Invoke-WebRequest -UseBasicParsing $env:MICRO_DOWNLOAD_URL -OutFile micro.zip; `
    Expand-Archive micro.zip -DestinationPath \; `
    Rename-Item -Path $('C:\micro-{0}' -f $env:MICRO_VERSION) -NewName "C:\micro"; `
    Remove-Item micro.zip;

ENV GIT_VERSION 2.20.1 `
    GIT_SHA256 9817ab455d9cbd0b09d8664b4afbe4bbf78d18b556b3541d09238501a749486c `
    GIT_DOWNLOAD_URL https://github.com/git-for-windows/git/releases/download/v${GIT_VERSION}.windows.1/MinGit-${GIT_VERSION}-busybox-64-bit.zip
RUN [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; `
    Invoke-WebRequest -UseBasicParsing $env:GIT_DOWNLOAD_URL -OutFile git.zip; `
    if ((Get-FileHash git.zip -Algorithm sha256).Hash -ne $env:GIT_SHA256) { `
      exit 1 `
    }; `
    Expand-Archive git.zip -DestinationPath \git; `
    Remove-Item git.zip -Force; `
    [Environment]::SetEnvironmentVariable('PATH', $env:Path + ';C:\git\cmd', [EnvironmentVariableTarget]::Machine);


ENV NODE_VERSION 10.15.0 `
    NODE_DOWNLOAD_URL https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-win-x64.zip
RUN Invoke-WebRequest -UseBasicParsing $env:NODE_DOWNLOAD_URL -OutFile 'node.zip'; `
    Expand-Archive node.zip -DestinationPath \; `
    Rename-Item -Path $('C:\node-v{0}-win-x64' -f $env:NODE_VERSION) -NewName 'C:\nodejs'; `
    Remove-Item node.zip -Force;


ENV PYTHON_VERSION 3.7.2 `
    PYTHON_DOWNLOAD_URL https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-amd64.exe
RUN [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; `
    Invoke-WebRequest -UseBasicParsing $env:PYTHON_DOWNLOAD_URL -OutFile python.exe; `
      Start-Process python.exe -Wait `
        -ArgumentList @( `
            '/quiet', `
            'InstallAllUsers=1', `
            'TargetDir=C:\Python', `
            'PrependPath=1', `
            'Shortcuts=0', `
            'Include_doc=0', `
            'Include_pip=1', `
            'Include_test=0', `
            'Include_tcltk=0' `
        ); `
    Remove-Item python.exe -Force; `
    $env:PATH = [Environment]::GetEnvironmentVariable('PATH', [EnvironmentVariableTarget]::Machine); `
    python -m pip install --upgrade pip;


ENV LLVM_VERSION 7.0.1 `
    LLVM_DOWNLOAD_URL https://releases.llvm.org/${LLVM_VERSION}/LLVM-${LLVM_VERSION}-win64.exe
RUN [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; `
    Invoke-WebRequest -UseBasicParsing $env:LLVM_DOWNLOAD_URL -OutFile llvm.exe; `
    .\llvm.exe /S | Out-Null; `
    Remove-Item llvm.exe -Force;


ENV GRCOV_VERSION 0.4.1 `
    GRCOV_DOWNLOAD_URL https://github.com/mozilla/grcov/releases/download/v${GRCOV_VERSION}/grcov-win-x86_64.tar.bz2
RUN [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; `
    Invoke-WebRequest -UseBasicParsing $env:GRCOV_DOWNLOAD_URL -OutFile grcov.tar.bz2; `
    7z x grcov.tar.bz2; `
    7z x grcov.tar; `
    Remove-Item grcov.tar.bz2;


RUN pip install git+https://github.com/mozillasecurity/fuzzfetch;

RUN pip install credstash

RUN git clone --depth 1 --no-tags https://github.com/mozillasecurity/fuzzmanager.git; `
    pip install ./fuzzmanager; `
    pip install boto;


FROM $target

ENV ProgramFiles C:\Program Files

USER Administrator

COPY --from=download ["/Program Files/7-Zip", "$ProgramFiles/7-Zip"]
COPY --from=download ["/nodejs", "$ProgramFiles/NodeJS"]
COPY --from=download ["/git", "$ProgramFiles/git"]
COPY --from=download ["/Python", "$ProgramFiles/Python"]
COPY --from=download ["/ripgrep/rg.exe", "/Windows/system32/rg.exe"]
COPY --from=download ["/Program Files/LLVM", "$ProgramFiles/LLVM"]
COPY --from=download ["/micro/micro.exe", "/Windows/system32/micro.exe"]
COPY --from=download ["/grcov.exe", "/windows/system32/grcov.exe"]
COPY --from=download ["/PowerShell", "$ProgramFiles/PowerShell"]
COPY --from=download ["/fuzzmanager", "/fuzzmanager"]

ARG SETX=/M
RUN setx %SETX% PATH "%PATH%;%ProgramFiles%\7-Zip;%ProgramFiles%\NodeJS;%ProgramFiles%\git\cmd;%ProgramFiles%\git\mingw64\bin;%ProgramFiles%\git\usr\bin;C:\Python\Scripts;%ProgramFiles%\Python;%ProgramFiles%\LLVM\bin;%ProgramFiles%\PowerShell"

CMD [ "pwsh" ]
