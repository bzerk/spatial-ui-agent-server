const scene=document.querySelector('#scene');const bearing=document.querySelector('#bearing');
function orient(pose){const yaw=pose.head.yawDeg;const normalized=((yaw%360)+360)%360;bearing.textContent=String(Math.round(normalized)).padStart(3,'0')+'°';scene.style.transform=`translateX(${Math.max(-42,Math.min(42,pose.stage.yawDeg*.9))}px) rotate(${pose.stage.rollDeg*.18}deg)`}
if(window.rokid?.spatial)window.rokid.spatial.subscribe(orient);else window.addEventListener('deviceorientation',event=>orient({head:{yawDeg:event.alpha||0},stage:{yawDeg:-(event.alpha||0),rollDeg:-(event.gamma||0)}}));
