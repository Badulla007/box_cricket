(() => {
  const cfg = window.BOUNDARY_TURF;
  const dateInput = document.getElementById('bookingDate');
  const duration = document.getElementById('durationHours');
  const start = document.getElementById('startTime');
  const message = document.getElementById('availabilityMessage');
  const submit = document.getElementById('bookButton');
  const estimate = document.getElementById('priceEstimate');
  if (!cfg || !dateInput || !duration || !start || !message || !submit) return;
  const money = value => new Intl.NumberFormat('en-IN', {style:'currency',currency:'INR',maximumFractionDigits:0}).format(value);
  async function loadSlots() {
    submit.disabled = true;
    message.textContent = 'Checking live availability…';
    start.replaceChildren(new Option('Loading slots…', ''));
    try {
      const url = new URL(cfg.slotsUrl, window.location.origin);
      url.searchParams.set('date', dateInput.value);
      url.searchParams.set('hours', duration.value);
      const response = await fetch(url, {headers:{Accept:'application/json'}});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not check availability.');
      start.replaceChildren();
      let count = 0;
      data.slots.forEach(slot => {
        const opt = new Option(`${slot.label} · ${slot.available ? 'Available' : slot.reason}`, slot.start);
        opt.disabled = !slot.available;
        start.add(opt);
        if (slot.available) count++;
      });
      if (!data.slots.length) start.add(new Option('No slots for this date', ''));
      message.textContent = data.message || (count ? `${count} start times available.` : 'No available slots. Try another date.');
      submit.disabled = count === 0;
    } catch (error) {
      start.replaceChildren(new Option('Availability unavailable', ''));
      message.textContent = error.message;
      submit.disabled = true;
    }
    estimate.textContent = `${money(cfg.price)} × ${duration.value} = ${money(cfg.price * Number(duration.value))}`;
  }
  dateInput.addEventListener('change', loadSlots);
  duration.addEventListener('change', loadSlots);
  loadSlots();
})();
