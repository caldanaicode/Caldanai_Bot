
function onTemplateChanged(event) {
	document.querySelector("div#template").innerHTML = `${event.target.id}`;
}

document.querySelectorAll("input[name='template']").forEach(
	input => { input.addEventListener("change", onTemplateChanged) }
)