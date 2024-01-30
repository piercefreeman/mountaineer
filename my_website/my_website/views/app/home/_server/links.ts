export const getLink = ({
home_id
} : {
home_id: string
}) => {
let url = '/home/{home_id}/';

const queryParameters : Record<string, string> = {

};
const pathParameters : Record<string, string> = {
home_id
};

const parsedParams = Object.entries(queryParameters).reduce((acc, [key, value]) => {
if (value !== undefined) {
acc.push(`${key}=${value}`);
}
return acc;
}, [] as string[]);

const paramString = parsedParams.join('&');

for (const [key, value] of Object.entries(pathParameters)) {
if (value === undefined) {
throw new Error(`Missing required path parameter ${key}`);
}
url = url.replace(`{${key}}`, value);
}

if (paramString) {
url = `${url}?${paramString}`;
}

return url;
};