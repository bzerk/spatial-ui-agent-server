const scene=document.querySelector('#scene');const bearing=document.querySelector('#bearing');
function orient(yaw){const normalized=((yaw%360)+360)%360;bearing.textContent=String(Math.round(normalized)).padStart(3,'0')+'°';scene.style.transform=`translateX(${Math.sin(yaw*Math.PI/180)*18}px)`}
window.addEventListener('deviceorientation',event=>orient(event.alpha||0));
window.addEventListener('spatialorientation',event=>orient(event.detail.yaw||0));
