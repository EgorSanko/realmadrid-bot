@echo off
mkdir "C:\Users\egor3\Projects\real-madrid\RealMadridBot\backups" 2>nul
scp root@81.17.154.4:/root/backups/*.db "C:\Users\egor3\Projects\real-madrid\RealMadridBot\backups\"
echo Backup downloaded!
pause