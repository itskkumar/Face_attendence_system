export const THEME_KEY = "fa-theme";
// Runs before first paint (inline in <head>) so the saved light theme does not flash dark.
export const THEME_INIT_SCRIPT = `try{if(localStorage.getItem("${THEME_KEY}")==="light")document.documentElement.classList.add("light")}catch(e){}`;
