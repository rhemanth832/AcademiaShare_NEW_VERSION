// All accounts, classes, files, exams, results, and notifications use Django.
let csrf = '';
async function csrfToken() {
  const response = await fetch('/api/auth/csrf/', {credentials:'same-origin', cache:'no-store'});
  if (!response.ok) throw new Error('The application server is unavailable. Please try again shortly.');
  csrf = (await response.json()).csrfToken;
  return csrf;
}
export async function request(path, method='GET', body) {
  if(method!=='GET'&&!csrf) await csrfToken();
  const headers={Accept:'application/json',...(method!=='GET'?{'X-CSRFToken':csrf}:{}),...(body&&!(body instanceof FormData)?{'Content-Type':'application/json'}:{})};
  let response;
  try {
    response=await fetch(`/api/${path}`,{method,headers,credentials:'same-origin',cache:'no-store',body:body?(body instanceof FormData?body:JSON.stringify(body)):undefined});
  } catch {
    throw new Error('Cannot reach the application server. Check your connection and try again.');
  }
  let data;
  try {data=await response.json();}
  catch {throw new Error('The application server did not respond correctly. Please try again shortly.');}
  if(!response.ok){const error=new Error(data.error||'Please try again.');error.status=response.status;if(response.status===403)csrf='';throw error;}
  if(path.startsWith('auth/'))csrf='';
  return data;
}
export async function getBlob(url) {
  const parsed=new URL(url,location.origin);
  if(parsed.origin!==location.origin)throw new Error('This download does not belong to this workspace.');
  const response=await fetch(parsed.href,{credentials:'same-origin',cache:'no-store'});
  if(!response.ok)throw new Error('You cannot download this file.');
  return response.blob();
}
export async function download(file) {
  const blob=await getBlob(file.download_url),url=URL.createObjectURL(blob),anchor=document.createElement('a');
  anchor.href=url;anchor.download=file.name;document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
}
