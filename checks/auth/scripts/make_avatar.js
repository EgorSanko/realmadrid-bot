// Тестовая «фотография профиля» (JPEG 320×320) — её отдаёт подставной t.me в local_backend.py.
//   NODE_PATH=C:/Users/egor3/node_modules node make_avatar.js <out.jpg>
const { chromium } = require('playwright');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const data = await page.evaluate(() => {
    const c = document.createElement('canvas');
    c.width = c.height = 320;
    const g = c.getContext('2d');
    const bg = g.createLinearGradient(0, 0, 320, 320);
    bg.addColorStop(0, '#2a3350');
    bg.addColorStop(1, '#0d1020');
    g.fillStyle = bg;
    g.fillRect(0, 0, 320, 320);
    g.fillStyle = '#e9d39a';
    g.beginPath();
    g.arc(160, 128, 62, 0, Math.PI * 2);
    g.fill();
    g.beginPath();
    g.ellipse(160, 330, 120, 110, 0, Math.PI, 0);
    g.fill();
    g.fillStyle = '#1b2240';
    g.font = 'bold 54px sans-serif';
    g.textAlign = 'center';
    g.fillText('АМ', 160, 147);
    return c.toDataURL('image/jpeg', 0.9);
  });
  fs.writeFileSync(process.argv[2], Buffer.from(data.split(',')[1], 'base64'));
  await browser.close();
})();
