window.JModiSend = (t) => { try { const r = window.Android.modusCmd(t); if (window.JModiToast) window.JModiToast(r); } catch (e) {} };
window.JModiSaveCfg = (c) => { try { window.Android.setModiCfg(JSON.stringify(c)); } catch (e) {} };
