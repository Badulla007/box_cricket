(() => {
  const mapNode = document.getElementById('turfMap');
  const message = document.getElementById('mapMessage');
  let map, markers = [];
  const esc = s => String(s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function loadTurfs() {
    try {
      const response = await fetch('/api/turfs');
      const turfs = await response.json();
      const valid = turfs.filter(t => Number.isFinite(Number(t.lat)) && Number.isFinite(Number(t.lng)));
      if (!window.L || !mapNode) return;
      map = L.map(mapNode, {scrollWheelZoom:false}).setView([17.385,78.4867], 11);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:19, attribution:'&copy; OpenStreetMap'}).addTo(map);
      valid.forEach(t => {
        const marker = L.marker([Number(t.lat),Number(t.lng)]).addTo(map).bindPopup(`<b>${esc(t.name)}</b><br>${esc(t.locality || t.city)}<br>₹${Math.round(t.price)}/hour<br><a href="${esc(t.url)}">View turf</a>`);
        markers.push(marker);
      });
      if (valid.length) map.fitBounds(L.featureGroup(markers).getBounds().pad(.2));
      else message.textContent = 'No mapped, registered turf coordinates yet. Ask Admin to add map coordinates.';
    } catch (_) { if (message) message.textContent = 'The turf map could not be loaded. The list above is still available.'; }
  }
  loadTurfs();
  const locate = document.getElementById('locateMe');
  if (locate) locate.addEventListener('click', () => {
    if (!navigator.geolocation || !map) { if (message) message.textContent = 'Location is not available in this browser.'; return; }
    locate.disabled = true; locate.textContent = 'Finding location…';
    navigator.geolocation.getCurrentPosition(pos => {
      const here = [pos.coords.latitude,pos.coords.longitude];
      L.circleMarker(here,{radius:8,color:'#147347',fillColor:'#bde7ca',fillOpacity:1}).addTo(map).bindPopup('Your location').openPopup();
      map.setView(here,13); locate.disabled = false; locate.textContent = 'Use my location';
      if (message) message.textContent = 'Map centered on your current location. Your location is not stored.';
    }, () => { locate.disabled = false; locate.textContent = 'Use my location'; if (message) message.textContent = 'Location permission was not granted.'; });
  });
  const discoverForm = document.getElementById('discoverForm');
  if (discoverForm) discoverForm.addEventListener('submit', async event => {
    event.preventDefault();
    const query = document.getElementById('discoverQuery').value.trim();
    const target = document.getElementById('discoverResults');
    target.textContent = 'Searching OpenStreetMap…';
    try {
      const response = await fetch('/api/discover-turfs?q=' + encodeURIComponent(query));
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'External search failed.');
      target.replaceChildren();
      if (!data.results.length) { const p=document.createElement('p'); p.className='small-note'; p.textContent=data.message; target.append(p); return; }
      data.results.forEach(item => {
        const card=document.createElement('article'); card.className='discover-result';
        const title=document.createElement('b'); title.textContent=item.name;
        const detail=document.createElement('p'); detail.textContent=item.address;
        const note=document.createElement('p'); note.textContent=item.note;
        card.append(title,detail,note); target.append(card);
      });
      const note=document.createElement('p'); note.className='small-note'; note.textContent=data.message; target.append(note);
    } catch (error) { target.textContent=error.message; }
  });
})();
