document.addEventListener("DOMContentLoaded",()=>{
  const today=new Date().toISOString().slice(0,10);
  const start=document.querySelector("#start_date"), end=document.querySelector("#end_date");
  if(start){start.min=today;start.addEventListener("change",()=>{end.min=start.value;if(end.value<start.value)end.value=start.value;});}
  document.querySelectorAll("[data-destination]").forEach(btn=>btn.addEventListener("click",()=>{
    const input=document.querySelector('input[name="destination"]');
    if(input){input.value=btn.dataset.destination;document.querySelector("#explore").scrollIntoView({behavior:"smooth"});}
  }));
  const weatherBtn=document.querySelector("#weather-btn");
  if(weatherBtn) weatherBtn.addEventListener("click",async()=>{
    const out=document.querySelector("#weather-output");out.textContent="Loading forecast…";
    try{const r=await fetch(`/weather?place=${encodeURIComponent(weatherBtn.dataset.place)}`);const d=await r.json();
      if(!r.ok)throw new Error(d.error||"Could not load weather.");
      const c=d.forecast.current, day=d.forecast.daily;
      out.innerHTML=`<b>${d.location}, ${d.country}</b><p>Now: ${c.temperature_2m}°C · Humidity: ${c.relative_humidity_2m}% · Wind: ${c.wind_speed_10m} km/h</p><p>Today: ${day.temperature_2m_min[0]}–${day.temperature_2m_max[0]}°C · Rain chance: ${day.precipitation_probability_max[0]}%</p><small>Weather data: Open-Meteo</small>`;
    }catch(e){out.textContent=e.message;}
  });
});
