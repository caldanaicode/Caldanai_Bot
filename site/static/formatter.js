itemFields = {
	name: {
		type: "textbox" ,
		title: "Item name, such as 'stick' or 'wondrous ball of yarn'",
		placeholder: "Item name",
		required: true,
		size: 30
	},
		
	article: {
		type: "textbox" ,
		title: "Article for the item, such as 'a', 'an', or 'some'",
		placeholder: "a",
		required: true,
		size: 4,
		maxlength: 4
	},
	
	description: {
		type: "textbox" ,
		title: "The item's description. Feel free to be a bit creative!",
		placeholder: "Some fun, descriptive text about this item.",
		required: true,
		size: 80
	},
	
	weight: {
		type: "number" ,
		title: "The item's weight in pounds, such as 1.0 or 5.2",
		placeholder: 1.0,
		required: true,
		size: 7,
		min: 0.01,
		value: 1.0,
		step: 0.01
	},
	
	value: {
		type: "number" ,
		title: "The item's value in clarks, as a whole number.",
		placeholder: 0,
		required: true,
		size: 7,
		min: 0,
		step: 1
	},
	
	image: {
		type: "textbox" ,
		title: "A free-use image to represent the item. This will be modified if necessary.",
		placeholder: "https://some.url/image.png",
		size: 80
	},
};

weaponFields = {
	name: {
		type: "textbox" ,
		title: "Weapon name, such as 'staff' or 'greatsword of flaming impunity'",
		placeholder: "Weapon name",
		required: true,
		size: 30
	},
		
	article: {
		type: "textbox" ,
		title: "Article for the weapon, such as 'a', or 'an'",
		placeholder: "a",
		required: true,
		size: 4,
		maxlength: 4
	},
	
	description: {
		type: "textbox" ,
		title: "The weapon's description. Feel free to be a bit creative!",
		placeholder: "Some fun, descriptive text about this weapon, possible some lore.",
		required: true,
		size: 80
	},
	
	weight: {
		type: "number" ,
		title: "The weapon's weight in pounds, such as 1.0 or 5.2",
		placeholder: 1.0,
		required: true,
		size: 7,
		min: 0.01,
		value: 1.0,
		step: 0.01
	},
	
	value: {
		type: "number" ,
		title: "The weapon's value in clarks, as a whole number.",
		placeholder: 0,
		required: true,
		size: 7,
		min: 0,
		step: 1
	},
	
	image: {
		type: "textbox" ,
		title: "A free-use image to represent the weapon. This will be modified if necessary.",
		placeholder: "https://some.url/image.png",
		size: 80
	},

	attack: {
		type: "textbox" ,
		title: "Article for the weapon, such as 'a', or 'an'",
		placeholder: "1d4",
		pattern: "\\d*[dD]\\d+",
		required: true,
		size: 8,
		maxlength: 8
	},
	
	isTwoHanded: {
		type: "checkbox",
		title: "Check the box if this is a two-handed weapon!"
	},
	
	attackMessage: {
		type: "textbox",
		title: "Currently unused, but should be something like 'stabs', 'swings', etc.",
		required: true,
		size: 10
	}
};

monsterFields = {
	name: {
		type: "textbox" ,
		title: "Monster's name, such as 'bearowl' or 'glittering dragon god'",
		placeholder: "monster name",
		required: true,
		size: 30
	},
	
	attack: {
		type: "textbox",
		title: "Monster's attack, in NdN format, such as '1d6' or '3d4'.",
		placeholder: "1d8",
		pattern: "\\d*[dD]\\d+",
		required: true,
		size: 8,
		maxlength: 8
	},
	
	defense: {
		type: "textbox",
		title: "Monster's defense (how much damage the monster absorbs before health is taken), in NdN format, such as '1d6' or '3d4'.",
		placeholder: "1d8",
		pattern: "\\d*[dD]\\d+",
		required: true,
		size: 8,
		maxlength: 8
	},
	
	dodge: {
		type: "textbox",
		title: "Monster's dodge (how hard it is to land a hit), in NdN format, such as '1d6' or '3d4'.",
		placeholder: "1d8",
		pattern: "\\d*[dD]\\d+",
		required: true,
		size: 8,
		maxlength: 8
	},
	
	health: {
		type: "textbox",
		title: "Monster's health, in NdN format, such as '1d6' or '3d4'.",
		placeholder: "1d8",
		pattern: "\\d*[dD]\\d+",
		required: true,
		size: 8,
		maxlength: 8
	},
	
	image: {
		type: "textbox",
		title: "Free-use image for the monster. This will be resized and altered as necessary.",
		placeholder: "https://some.url/image.png",
		size: 50
	},
	
	arrivals: {
		type: "textarea" ,
		title: "Randomly chosen arrival text, with a new line for each message.",
		required: true,
		rows: 6,
		cols: 80
	},
	
	flavors: {
		type: "textarea" ,
		title: "Randomly chosen descriptions, with a new line for each message.",
		required: true,
		rows: 6,
		cols: 80
	},
	
	hugs: {
		type: "textarea" ,
		title: "Randomly chosen responses for hugs, with a new line for each message.",
		required: true,
		rows: 6,
		cols: 80
	},
	
	escapes: {
		type: "textarea" ,
		title: "Randomly chosen escapes, with a new line for each message.",
		required: true,
		rows: 6,
		cols: 80
	},
	
	deaths: {
		type: "textarea" ,
		title: "Randomly chosen deaths, with a new line for each message.",
		required: true,
		rows: 6,
		cols: 80
	}
};

var output = document.querySelector("#format");
var fmt = {}

function copyFormat() {
	output.select();
	output.setSelectionRange(0, 99999); /* For mobile devices */
	document.execCommand("copy");
}

function displayFormat() {
	output.value = '';
	for (var field in fmt) {
		output.value += `"${field}": `;
		v = fmt[field];
		if (Array.isArray(v)) {
			output.value += '[';
			for (var l in v) {
				output.value += `\n\t"${v[l]}",`;
			}
			if (output.value.endsWith(','))
				output.value = output.value.substring(0, output.value.length - 1) + '\n';
			output.value += '],\n';
		}
		else {
			output.value += `${typeof(v) == 'string' ? '"' : '' }${v}${typeof(v) == 'string' ? '"' : '' },\n`;
		}
	}
	output.value = output.value.substring(0, output.value.length - 2);
}

function changeFormat(format) {
	fmt = {}
	for (var field in format) {
		switch(format[field].type) {
			case 'textbox':
				fmt[field] = '';
				break;
			case 'textarea':
				fmt[field] = [];
				break;
			case 'number':
				fmt[field] = format[field].min;
				break;
			case 'checkbox':
				fmt[field] = false;
				break;
		}
	}
	displayFormat();
}

function updateFormat(elmt) {
	if (!validate(elmt))
		return;
		
	val = elmt.value;
	switch(elmt.type) {
	    case 'number':
	        fmt[elmt.name] = Number(val);
	        break;
	    case 'textarea':
	        fmt[elmt.name] = val.trim().split('\n').filter( line => { return line.length > 0; } );
	        break;
	    case 'checkbox':
	        fmt[elmt.name] = elmt.checked
	        break;
	    default:
	        fmt[elmt.name] = val.trim();
	}
	displayFormat();
}

function validate(elmt) {
	if (elmt.validity.valid) {
		elmt.classList.remove('error');
		return true;
	}
	elmt.classList.add('error');
	return false;
}

function buildInput(name, input) {
	html = `<label for="${name}" class="l">${name}</label><br><${input.type == 'textarea' ? input.type : 'input type="' + input.type + '"'} name="${name}" class="f" oninput="updateFormat(this)"`;
	for (var field in input) {
		if (field != 'type') {
			if (field == 'required') {
				html += ' required';
			}
			else {
				html += ` ${field}="${input[field]}"`;
				if (field == 'pattern') {
					html += `oninput="validate(this.value, ${input[field]})"`;
				}
			}
		}
	}
	html += `>${input.type == 'textarea' ? '</textarea>' : ''}<br>`;
	return html;
}

function buildForm(title, fields) {
	fmt = {}
	html = `<h1 class='h'>${title}</h1>`;
	for (var field in fields) {
		html += buildInput(field, fields[field]);
	}
	document.querySelector("div#template").innerHTML = html;
	displayFormat();
}

function onTemplateChanged(event) {
	switch(event.target.id) {
		case 'item':
			buildForm("Item Builder", itemFields);
			changeFormat(itemFields);
			break;
		case 'weapon':
			buildForm("Weapon Builder", weaponFields);
			changeFormat(weaponFields);
			break;
		case 'monster':
			buildForm("Monster Builder", monsterFields);
			changeFormat(monsterFields);
			break;
	}
}

document.querySelectorAll("input[name='template']").forEach(
	input => { input.addEventListener("change", onTemplateChanged) }
);

buildForm("Item Builder", itemFields);
changeFormat(itemFields);