import re, unicodedata
G={'α':'a','β':'v','γ':'g','δ':'d','ε':'e','ζ':'z','η':'i','θ':'th','ι':'i','κ':'k','λ':'l','μ':'m','ν':'n','ξ':'x','ο':'o','π':'p','ρ':'r','σ':'s','ς':'s','τ':'t','υ':'y','φ':'f','χ':'ch','ψ':'ps','ω':'o'}
def strip(s):
    s=unicodedata.normalize('NFD',s)
    out=[]
    for ch in s:
        if ch=='\u0308': out.append('\u0308')   # keep diaeresis marker
        elif unicodedata.combining(ch): continue
        else: out.append(ch)
    return ''.join(out)
def elot_word(w):
    w=strip(w.lower()); res=''; i=0; n=len(w)
    while i<n:
        c=w[i]; nx=w[i+1] if i+1<n else ''; nn=w[i+2] if i+2<n else ''
        dia = nn=='\u0308'
        pair=c+nx
        if pair=='αι' and not dia: res+='ai'; i+=2; continue
        if pair=='ει' and not dia: res+='ei'; i+=2; continue
        if pair=='οι' and not dia: res+='oi'; i+=2; continue
        if pair=='υι' and not dia: res+='yi'; i+=2; continue
        if pair=='ου' and not dia: res+='ou'; i+=2; continue
        if pair=='μπ': res+= 'b' if i==0 else 'mp'; i+=2; continue
        if pair=='ντ': res+= 'd' if i==0 else 'nt'; i+=2; continue
        if pair=='γγ': res+='ng'; i+=2; continue
        if pair=='γκ': res+= 'g' if i==0 else 'ng'; i+=2; continue
        if pair=='γξ': res+='nx'; i+=2; continue
        if pair=='γχ': res+='nch'; i+=2; continue
        if c in 'αεη' and nx=='υ' and nn!='\u0308':
            after=w[i+2] if i+2<n else ''
            voiceless = after=='' or after in 'κξπσςτφχψθ'
            res+= {'α':'a','ε':'e','η':'i'}[c] + ('f' if voiceless else 'v'); i+=2; continue
        if c=='\u0308': i+=1; continue
        res+=G.get(c,c); i+=1
    return res
def elot(s):
    out=[]
    for tok in re.split(r'(\s+|-|\(|\)|,|\.|/)',s):
        if not tok or re.fullmatch(r'\s+|-|\(|\)|,|\.|/',tok): out.append(tok); continue
        t=elot_word(tok); out.append(t[:1].upper()+t[1:])
    return ''.join(out)
