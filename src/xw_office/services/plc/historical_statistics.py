"""Sanitised historical PLC aggregates imported from the Post export.

The source export is deliberately reduced to day, country, count, total weight
and calculated tariff. It contains no tracking, recipient, sender or other
personal data. Three rows without a supported tariff were omitted.
"""
from __future__ import annotations

import base64
import datetime
import json
import zlib
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from zoneinfo import ZoneInfo


_VIENNA = ZoneInfo("Europe/Vienna")


@dataclass(frozen=True)
class PlcHistoricalStatisticsRow:
    """One day/country aggregate from the historical Post export."""

    country_iso2: str
    shipment_count: int
    weight_kg: Decimal
    price_eur: Decimal
    printed_at: datetime.datetime


# Generated from docs/invoices/Sendungen_202609152152.csv on 15.09.2026.
# The compact payload consists only of [date, country, count, kg, price] rows.
_COMPRESSED_ROWS = (
    "c$|e;P0l4Z2)s+L`&n)9?=qT1%1BXGS!Fc$zeZ%BZ7|L^%O}+{7z(P|KYm>BK>j@a1L?Z2Z+~8QyssS6bKMt|fc5%$Z=m1*AW#Wy"
    "fFgv}7AQWSCoT|RD1_=E7LWS=&vnCnwNT4-Ul;>|1%Wy$;D{cd0FMO~0l|IsP{z5C$B711ulxG#AIY5lQUgSTi6|HxDJ6>5L#!S&"
    "qTzkT9Qyc)won6=<tVycrlY7722@tO7{?J5uy=!kXJw9|je|?T14inE0pqbw@Ln(8SK^#p2?#R|N_@KkN*I#uFsNc;z;aBf>eiKh"
    "PN@nBD5W-n#~g}oU1So>ybJie1@q=z#|ih9O31n^@$=x~ID|}P>XyC&5;`^JIAC}-(A(b;uZ=kO1=U_pP_qU#A8HUkPuC!-hzCVQ"
    "f*fcJT@7MfoGSsS;t*={Ah}({aRkk|A$eRR=bX-o$D~K9KgXQZ!T^qTI7rbchhC2dRWsxxKZv0v3u>B|#EFfUf{~0`sFV=}bs*s-"
    "hBgk0X-{bmCZ*KJUt$UgJZMfP-NF}u`Z*a+lye1`tCu%QKGJdy9gdslkvFsubxOdSclM2XvPBcj98743!GtxKgG*27@v!CK^C${D"
    "JmW3&?IhKdEbDU96<9L>1Jq9Z7Lb&w@JTyQ1SGeMB2ZwL1(<Pafr#ucM<CfKk>cDJ<^X6>#q_tIDo&Vh{|bhsE?GSk&>SbG+{Pv_"
    "438{OuHdo%lHl+GqrM~!J{oaD3XVg&yx7ABRV|ZDK^$5ppz?XtP9+dIf&-|0t#k}B+QaPiAj3JXrRE%gqACFfbR}4zH7sc#76v6H"
    "_Q<mt`*0!-CGk?g|4B*}Dn23OzIh0xeZyfrFU+g~nLZzmHpCYKwLp_loVX?wgG}>ihaFC;#udHxak(N!byb5n=f%`O*4P(*l|iP*"
    "$vG7Ur8S-~G=;;W2g&-ap$-r}YGp7;nF0*uR0LpCFqN$0reuWC`>+SPs##DBGMA$SeYB0h<v?ICDjnJJ<d6=SNtJe@irr5zHrxp`"
    "jVLd%wk<Kns7i|3`R;13npvZ^F+ihsb;zZ^Ke8`;?=OzFk0v|N;?i@t8!npAqHAttGUy%hr3XH5Re&T5dMg0(o?GIxfB7&*(G3C-"
    "YonWBX4}$fsp95Sb2|l_lq89!{=+kBWk9Oh5Gc0GNXu$wJMV+NWE<P0uohspOhRL>5`Xphlt6{6Ol}uWZ@3(CId){KA@9oS@0RRG"
    "v{<XH+R3mj@xIxk31|*?byki+h5#fBJ|+91a@vz=^^IH;RdQcS0-9AKo8j};-93D<FU;B!-EWD+R!1yaWgllAHWp}^0cSu7q=hhv"
    "BlI9cTw3q0l5@H7=5}7be4cC;fXLEzP&Tg`z`n|1Xx!E!IgDgBU8|y#Th|2iwKvIY-soxxk5|*yL==9LlFY@PS0jh&uBID8AN!|_"
    "w2Mt*bv;N4S7IB#gNE%edm9g1V$8RIGC71k7@A{vHk4{^4t;;qSeU6L^(5V84KDkj+z+i2lw_WHPJHItDu6tHxp;F>XnB*GnC~kB"
    "Y4MhiFkemm(OcNbyAtU4##br*L8_JytKh~a!7N=a$Ged@%t@hj>N7Itg{rY1RM%Jn)w$59)S;^erKRcN&5SrCN~81|1plV7F!Ofw"
    "fZ~&y!!nox@;IPhei&ue7v0u{)9ppMoe!r9g<_aJNXbs(0p2Pun7Nv13GEzcY^jzNIJhOjOzM(S@2g2be|>*T>7ED)q`&0=<TVP^"
    "Bho@mSII|h!rP3iMxLjw-pv^1B;UNQ0z}36`uEOUJ%HBhAHVW9`;FbqWXc1=Hc*0j$s6TcXCrT0qsfou^!*G^XtpubVJTD>XSq#F"
    "W7G8aUoSD`d(X7Eo2Oz7<)DXx`SQ!68)F6MSBB2}`F;C=fFxsme2yE`yHr@~@vxt}d5e%Y{zE*~;U;B*aY+Y~TDI{y>}%P#=UvuK"
    "7w#9&yNod&g=Eatn=q15mb7^ce*On^Zx!V"
)


@lru_cache(maxsize=1)
def historical_statistics_rows() -> tuple[PlcHistoricalStatisticsRow, ...]:
    """Return the import as compact, date-filterable aggregate rows."""
    payload = json.loads(zlib.decompress(base64.b85decode(_COMPRESSED_ROWS)).decode("utf-8"))
    return tuple(
        PlcHistoricalStatisticsRow(
            country_iso2=country,
            shipment_count=int(count),
            weight_kg=Decimal(weight_kg),
            price_eur=Decimal(price_eur),
            printed_at=datetime.datetime.fromisoformat(day).replace(tzinfo=_VIENNA),
        )
        for day, country, count, weight_kg, price_eur in payload
    )
