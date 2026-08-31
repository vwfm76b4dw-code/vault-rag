#include <bits/stdc++.h>
using namespace std;
int n; 
int main()
{
	int gong=7371;
	for(int x=7371;x<=99999;x+=gong){
		n++;
		int bai=x/100%10;
		if(bai==1){
			cout<<x<<endl;
			cout<<n;
			return 0;
		}
	}
}
