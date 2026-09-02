Name:           radmin-linux
Version:        0.1.0
Release:        1%{?dist}
Summary:        Run Radmin VPN (Windows-only) on Linux via a headless VM

License:        MIT
URL:            https://github.com/gabrielmf1998/radmin-linux
BuildArch:      noarch

Requires:       qemu-system-x86-core
Requires:       qemu-img
Requires:       dnsmasq
Requires:       NetworkManager
Requires:       socat
Requires:       python3 >= 3.11
Requires:       python3-pip
Recommends:     tigervnc

%description
Radmin VPN (Linux) drives the real Radmin VPN running inside a tiny headless
Windows VM, from a native Qt front-end. The user never opens the VM: the app
powers it on/off, shows the mesh, connects/disconnects and self-heals.
This package installs the front-end, agent scripts and the installer helper.
The VM image is provided separately (it is large and carries state).

%prep
# sources are laid down by the build script into %{_builddir}

%install
rm -rf %{buildroot}
install -d %{buildroot}%{_datadir}/radmin-linux
cp -r %{srcdir}/app %{srcdir}/shim %{srcdir}/agent %{buildroot}%{_datadir}/radmin-linux/
find %{buildroot}%{_datadir}/radmin-linux -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
install -m644 %{srcdir}/env.sh %{buildroot}%{_datadir}/radmin-linux/
install -m755 %{srcdir}/preflight.sh %{srcdir}/radmin-linux.sh %{srcdir}/deploy-shim.sh \
        %{srcdir}/deploy-agent.sh %{srcdir}/install.sh %{srcdir}/build-vm.sh \
        %{buildroot}%{_datadir}/radmin-linux/
install -d %{buildroot}%{_bindir}
ln -s %{_datadir}/radmin-linux/radmin-linux.sh %{buildroot}%{_bindir}/radmin-linux
install -d %{buildroot}%{_datadir}/applications
install -m644 %{srcdir}/packaging/radmin-linux.desktop %{buildroot}%{_datadir}/applications/

%files
%{_datadir}/radmin-linux/
%{_bindir}/radmin-linux
%{_datadir}/applications/radmin-linux.desktop

%post
echo "Radmin-Linux instalado. Finalize com:"
echo "  radmin-linux            (a UI monta a pilha na 1a execucao)"
echo "ou forneca a imagem da VM: %{_datadir}/radmin-linux/install.sh IMG.qcow2.zst"

%changelog
* Wed Sep 02 2026 gabrielmf1998 <110578985+gabrielmf1998@users.noreply.github.com> - 0.1.0-1
- Primeira versao empacotada
