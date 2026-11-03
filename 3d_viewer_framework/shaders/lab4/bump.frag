//VTK::System::Dec
//VTK::Output::Dec
in vec3 positionVC,normalVC;
in vec2 uv;
uniform sampler2D lab4Height,actortexture;
uniform vec2 lab4Tiling;
uniform float lab4Strength,lab4Diffuse,lab4Specular,lab4Shininess,lab4Ambient,lab4LightPower;
uniform int lab4HasAlbedo;
uniform vec3 lab4Color,lab4Emission,lab4LightVC,lab4LightColor;
void main() {
    vec3 n=normalize(normalVC);
    if(!gl_FrontFacing) n=-n;
    vec2 q=uv*lab4Tiling,texel=1.0/vec2(textureSize(lab4Height,0));
    float hu=(texture(lab4Height,q+vec2(texel.x,0)).r-texture(lab4Height,q-vec2(texel.x,0)).r)/(2.0*texel.x)*lab4Tiling.x;
    float hv=(texture(lab4Height,q+vec2(0,texel.y)).r-texture(lab4Height,q-vec2(0,texel.y)).r)/(2.0*texel.y)*lab4Tiling.y;
    vec3 dx=dFdx(positionVC),dy=dFdy(positionVC);
    vec2 tx=dFdx(uv),ty=dFdy(uv);
    float det=tx.x*ty.y-tx.y*ty.x;
    if(abs(det)>1e-12) {
        vec3 pu=(dx*ty.y-dy*tx.y)/det,pv=(dy*tx.x-dx*ty.x)/det;
        pu-=n*dot(n,pu); pv-=n*dot(n,pv);
        float a=dot(pu,pu),b=dot(pu,pv),c=dot(pv,pv),g=a*c-b*b;
        if(g>1e-12) n=normalize(n-lab4Strength*((c*hu-b*hv)*pu+(a*hv-b*hu)*pv)/g);
    }
    vec3 l=normalize(lab4LightVC-positionVC),v=normalize(-positionVC);
    float diffuse=max(dot(n,l),0.0);
    float spec=diffuse>0.0?pow(max(dot(n,normalize(l+v)),0.0),lab4Shininess):0.0;
    vec3 color=lab4Color;
    if(lab4HasAlbedo!=0) color*=texture(actortexture,uv).rgb;
    vec3 c=color*(lab4Ambient+lab4LightPower*lab4Diffuse*diffuse)*lab4LightColor+
           vec3(lab4Specular*spec*lab4LightPower)+lab4Emission;
    gl_FragData[0]=vec4(c,1.0);
}
