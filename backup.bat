@echo off
mkdir "C:\Users\egor3\Desktop\RealMadridBot\backups" 2>nul
scp root@81.17.154.4:/root/backups/*.db "C:\Users\egor3\Desktop\RealMadridBot\backups\"
echo Backup downloaded!
pause