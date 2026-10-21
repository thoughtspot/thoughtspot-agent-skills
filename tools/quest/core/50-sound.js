// ---- Sound: generated with the Web Audio API, so there are no audio files and no requests. ----
// Effects are on by default, music is off; both toggles are remembered. Browsers only allow
// audio after the player clicks or presses a key, so nothing plays before that.
var Quest = (typeof Quest === "object" && Quest) || {};
(function (Q) {
  "use strict";
  Q.sound = (storageKey, S) => {
    const AC = typeof AudioContext !== "undefined" ? AudioContext
      : typeof webkitAudioContext !== "undefined" ? webkitAudioContext : null;
    const prefs = { sfx: true, music: false };
    try { Object.assign(prefs, JSON.parse(localStorage.getItem(`${storageKey}-sound`) || "{}")); } catch {}
    const save = () => { try { localStorage.setItem(`${storageKey}-sound`, JSON.stringify(prefs)); } catch {} };
    let ctx = null, master = null, musicBus = null, unlocked = false;
    let track = null, want = null, timer = null, lead = { i: 0, t: 0 }, bass = { i: 0, t: 0 };
    const hz = n => 440 * Math.pow(2, (n - 69) / 12);          // MIDI note number to frequency

    let broken = false;                                        // audio failed once: stay silent
    function ensure() {
      if (!AC || !unlocked || broken) return false;
      try {
        if (!ctx) {
          ctx = new AC();
          master = ctx.createGain(); master.gain.value = 0.16; master.connect(ctx.destination);
          musicBus = ctx.createGain(); musicBus.gain.value = 0.45; musicBus.connect(master);
        }
        if (ctx.state === "suspended") ctx.resume();
        return true;
      } catch { broken = true; return false; }
    }
    function tone(freq, at, dur, type = "square", vol = 0.5, dest = master, slideTo = 0) {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = type;
      o.frequency.setValueAtTime(freq, at);
      if (slideTo) o.frequency.exponentialRampToValueAtTime(slideTo, at + dur);
      g.gain.setValueAtTime(vol, at);
      g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
      o.connect(g); g.connect(dest);
      o.start(at); o.stop(at + dur + 0.02);
    }
    const EFFECTS = {
      coin: t => { tone(hz(83), t, 0.07); tone(hz(88), t + 0.07, 0.25); },                 // gold
      steal: t => { [88, 83, 79, 76].forEach((n, i) => tone(hz(n), t + i * 0.06, 0.07, "square", 0.3));  // coins tumbling away
                    tone(130, t + 0.26, 0.3, "sawtooth", 0.35, master, 65); },
      magic: t => [84, 88, 91, 96, 91, 96].forEach((n, i) => tone(hz(n), t + i * 0.05, 0.18, "triangle", 0.35)),
      fanfare: t => [72, 76, 79, 84].forEach((n, i) => tone(hz(n), t + i * 0.11, i === 3 ? 0.5 : 0.12)),
      blip: t => tone(hz(81), t, 0.045, "square", 0.2)
    };
    // Original loops, written for this game: [MIDI note or 0 for a rest, beats].
    const TRACKS = {
      map: { bpm: 96,
        lead: [[72,1],[76,1],[79,1],[76,1],[77,1],[74,1],[71,2],[72,1],[74,1],[76,1],[79,1],[77,2],[74,2]],
        bass: [[48,2],[55,2],[53,2],[55,2],[48,2],[52,2],[53,2],[55,2]] },
      court: { bpm: 80,
        lead: [[74,2],[77,1],[76,1],[74,2],[69,2],[70,2],[72,1],[70,1],[69,4]],
        bass: [[50,4],[46,4],[43,4],[45,4]] },
      battle: { bpm: 132,
        lead: [[69,.5],[72,.5],[76,.5],[72,.5],[69,.5],[72,.5],[77,.5],[72,.5],[67,.5],[71,.5],[74,.5],[71,.5],[68,.5],[71,.5],[76,1]],
        bass: [[45,1],[45,1],[41,1],[41,1],[43,1],[43,1],[40,1],[40,1]] }
    };
    function voice(part, notes, spb, type, vol) {
      while (part.t < ctx.currentTime + 0.25) {
        const [n, beats] = notes[part.i % notes.length];
        if (n) tone(hz(n), part.t, beats * spb * 0.85, type, vol, musicBus);
        part.t += beats * spb; part.i++;
      }
    }
    function stopMusic() { clearInterval(timer); timer = null; track = null; }
    function startMusic(name) {
      if (!prefs.music || !name || !ensure() || document.hidden) return stopMusic();
      if (track === name && timer) return;
      stopMusic();
      track = name;
      const tr = TRACKS[name], spb = 60 / tr.bpm, t0 = ctx.currentTime + 0.05;
      lead = { i: 0, t: t0 }; bass = { i: 0, t: t0 };
      const tick = () => { voice(lead, tr.lead, spb, "square", 0.22); voice(bass, tr.bass, spb, "triangle", 0.5); };
      tick(); timer = setInterval(tick, 100);
    }
    function label() {
      const fx = document.getElementById("sound-sfx"), mu = document.getElementById("sound-music");
      if (!fx || !mu || !fx.setAttribute) return;
      fx.textContent = S("sound_sfx", { state: S(prefs.sfx ? "sound_on" : "sound_off") });
      mu.textContent = S("sound_music", { state: S(prefs.music ? "sound_on" : "sound_off") });
      fx.setAttribute("aria-pressed", String(prefs.sfx));
      mu.setAttribute("aria-pressed", String(prefs.music));
    }
    return {
      prefs,
      unlock() { unlocked = true; try { startMusic(want); } catch { broken = true; } },
      play(name) { try { if (prefs.sfx && ensure()) EFFECTS[name](ctx.currentTime + 0.01); } catch { broken = true; } },
      music(name) { want = name; try { startMusic(name); } catch { broken = true; } },
      toggle(which) {
        prefs[which] = !prefs[which]; save(); label();
        if (which === "music") startMusic(want);
        else if (prefs.sfx) this.play("blip");
      },
      pause() { stopMusic(); },
      resume() { startMusic(want); },
      label
    };
  };
})(Quest);
